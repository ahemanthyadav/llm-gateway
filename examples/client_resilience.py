#!/usr/bin/env python3
"""Client resilience example for llm-gateway.

Demonstrates production-grade client behavior when calling the gateway:

- Retry with exponential backoff on 429 (rate limited) and 5xx errors
- Respect Retry-After header when present
- Fail fast on 401/403 (auth errors — retrying won't help)
- Degrade gracefully when the gateway is down (never block the calling app)
- Log which model actually answered (response `model` field)

Usage:
    python3 examples/client_resilience.py \
        --base-url http://<node>:30400/v1 \
        --key <project-key> \
        --capability fast-json \
        --prompt "Reply with exactly: OK"

Requires: pip install requests
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Optional

try:
    import requests
except ImportError:  # pragma: no cover - requests is optional for this example
    requests = None


def _ensure_requests() -> None:
    if requests is None:
        print("requests package not installed. Install with: pip install requests", file=sys.stderr)
        sys.exit(1)


class GatewayClient:
    """Resilient llm-gateway client with retry and graceful degradation."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0,
                 max_retries: int = 3, base_backoff: float = 1.0,
                 degrade_on_failure: bool = True) -> None:
        _ensure_requests()
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.degrade_on_failure = degrade_on_failure
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def chat(self, model: str, prompt: str, max_tokens: int = 64,
             temperature: float = 0.0) -> Optional[dict]:
        """Send a chat completion with retry logic.

        Returns the parsed JSON response, or None if degradation is enabled
        and all retries failed.
        """
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    timeout=self.timeout,
                )

                # Success
                if resp.status_code == 200:
                    data = resp.json()
                    model_used = data.get("model", "unknown")
                    content = data["choices"][0]["message"]["content"]
                    print(f"  [attempt {attempt + 1}] model={model_used} "
                          f"content={content!r}")
                    return data

                # Auth errors — never retry
                if resp.status_code in (401, 403):
                    print(f"  [attempt {attempt + 1}] HTTP {resp.status_code} "
                          f"— auth error, not retrying: {resp.text[:200]}")
                    if self.degrade_on_failure:
                        return None
                    raise RuntimeError(f"Auth error {resp.status_code}: {resp.text[:200]}")

                # Rate limited — retry with backoff, honor Retry-After
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else self._backoff(attempt)
                    print(f"  [attempt {attempt + 1}] HTTP 429 rate-limited, "
                          f"retrying in {wait:.1f}s")
                    last_error = f"HTTP 429: {resp.text[:200]}"
                    time.sleep(wait)
                    continue

                # Server errors — retry with backoff
                if 500 <= resp.status_code < 600:
                    wait = self._backoff(attempt)
                    print(f"  [attempt {attempt + 1}] HTTP {resp.status_code} "
                          f"server error, retrying in {wait:.1f}s")
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    time.sleep(wait)
                    continue

                # Other client errors — don't retry
                print(f"  [attempt {attempt + 1}] HTTP {resp.status_code} "
                      f"— not retrying: {resp.text[:200]}")
                if self.degrade_on_failure:
                    return None
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            except requests.exceptions.ConnectionError as e:
                wait = self._backoff(attempt)
                print(f"  [attempt {attempt + 1}] connection error, retrying in {wait:.1f}s: {e}")
                last_error = str(e)
                time.sleep(wait)
            except requests.exceptions.Timeout as e:
                wait = self._backoff(attempt)
                print(f"  [attempt {attempt + 1}] timeout, retrying in {wait:.1f}s: {e}")
                last_error = str(e)
                time.sleep(wait)

        print(f"  All {self.max_retries + 1} attempts failed. Last error: {last_error}")
        if self.degrade_on_failure:
            print("  Degrading: returning None (caller should handle gracefully)")
            return None
        raise RuntimeError(f"All retries failed: {last_error}")

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff: base * 2^attempt, capped at 30s."""
        return min(self.base_backoff * (2 ** attempt), 30.0)

    def health(self) -> bool:
        """Check gateway health. Returns True if reachable."""
        try:
            resp = self.session.get(f"{self.base_url}/health/liveliness", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Resilient llm-gateway client example")
    parser.add_argument("--base-url", required=True,
                        help="Gateway base URL (e.g. http://<node>:30400/v1)")
    parser.add_argument("--key", required=True, help="Project API key")
    parser.add_argument("--capability", default="fast-json",
                        help="Capability name to route through (default: fast-json)")
    parser.add_argument("--prompt", default="Reply with exactly: OK",
                        help="Prompt to send")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="Maximum retry attempts (default: 3)")
    parser.add_argument("--no-degrade", action="store_true",
                        help="Raise exception instead of degrading on failure")
    args = parser.parse_args()

    client = GatewayClient(
        base_url=args.base_url,
        api_key=args.key,
        max_retries=args.max_retries,
        degrade_on_failure=not args.no_degrade,
    )

    # Check health first
    if not client.health():
        print("Gateway is unreachable — degrading gracefully")
        if args.no_degrade:
            sys.exit(1)
        return

    print(f"Calling capability={args.capability} with prompt={args.prompt!r}")
    result = client.chat(model=args.capability, prompt=args.prompt)

    if result is None:
        print("Request degraded — no response from gateway")
    else:
        print(f"Success: {result['choices'][0]['message']['content']!r}")


if __name__ == "__main__":
    main()
