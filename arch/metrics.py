#!/usr/bin/env python3
"""Prometheus metrics for llm-gateway.

Defines all metrics that the gateway should emit for observability and alerting.
This module is framework-agnostic — it provides metric definitions and helper
functions that can be called from LiteLLM callbacks, middleware, or the admin UI.

To expose these metrics, run a Prometheus client HTTP server (e.g., on port 9090)
alongside the gateway, or push to a Pushgateway.

Metrics:
    llm_gateway_requests_total      Counter — total requests by capability, model, status
    llm_gateway_request_duration_seconds  Histogram — request latency by capability
    llm_gateway_rate_limited_total  Counter — requests rejected due to per-key RPM limit
    llm_gateway_budget_blocked_total  Counter — requests rejected due to budget exceeded
    llm_gateway_budget_spent_usd    Gauge — cumulative USD spend per key
    llm_gateway_budget_remaining_usd  Gauge — remaining USD budget per key
    llm_gateway_failover_total      Counter — fallback chain invocations (primary -> fallback)
    llm_gateway_uptime_seconds      Gauge — gateway uptime

Metric objects are created lazily on first use so the module imports cleanly
even when prometheus_client is not installed.
"""
from __future__ import annotations

import time
from typing import Optional

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
except ImportError:  # pragma: no cover - prometheus_client is optional
    Counter = Gauge = Histogram = start_http_server = None


def _ensure_prometheus() -> None:
    if Counter is None:
        raise ImportError(
            "prometheus_client not installed. Install with: pip install prometheus_client"
        )


_metrics_created = False


def _create_metrics() -> None:
    """Create Prometheus metric objects. Safe to call multiple times."""
    global _metrics_created
    if _metrics_created:
        return
    _ensure_prometheus()

    global REQUESTS_TOTAL, REQUEST_DURATION_SECONDS, RATE_LIMITED_TOTAL
    global BUDGET_BLOCKED_TOTAL, BUDGET_SPENT_USD, BUDGET_REMAINING_USD
    global FAILOVER_TOTAL, UPTIME_SECONDS, _start_time

    REQUESTS_TOTAL = Counter(
        "llm_gateway_requests_total",
        "Total LLM gateway requests",
        ["capability", "model", "provider", "status"],
    )

    REQUEST_DURATION_SECONDS = Histogram(
        "llm_gateway_request_duration_seconds",
        "Request latency in seconds",
        ["capability", "model"],
        buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 240.0),
    )

    RATE_LIMITED_TOTAL = Counter(
        "llm_gateway_rate_limited_total",
        "Total requests rejected due to per-key RPM limit",
        ["key_alias"],
    )

    BUDGET_BLOCKED_TOTAL = Counter(
        "llm_gateway_budget_blocked_total",
        "Total requests rejected due to budget exceeded",
        ["key_alias"],
    )

    BUDGET_SPENT_USD = Gauge(
        "llm_gateway_budget_spent_usd",
        "Cumulative USD spend per key",
        ["key_alias"],
    )

    BUDGET_REMAINING_USD = Gauge(
        "llm_gateway_budget_remaining_usd",
        "Remaining USD budget per key",
        ["key_alias"],
    )

    FAILOVER_TOTAL = Counter(
        "llm_gateway_failover_total",
        "Total fallback chain invocations (primary -> fallback)",
        ["capability", "from_model", "to_model"],
    )

    UPTIME_SECONDS = Gauge(
        "llm_gateway_uptime_seconds",
        "Gateway uptime in seconds",
    )

    _start_time = time.time()
    _metrics_created = True


# ──────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────


def record_request(capability: str, model: str, provider: str,
                   status: str, duration_seconds: float) -> None:
    """Record a completed request."""
    _create_metrics()
    REQUESTS_TOTAL.labels(
        capability=capability, model=model, provider=provider, status=status
    ).inc()
    REQUEST_DURATION_SECONDS.labels(capability=capability, model=model).observe(
        duration_seconds
    )
    UPTIME_SECONDS.set(time.time() - _start_time)


def record_rate_limit(key_alias: str) -> None:
    """Record a rate-limited request."""
    _create_metrics()
    RATE_LIMITED_TOTAL.labels(key_alias=key_alias).inc()


def record_budget_block(key_alias: str) -> None:
    """Record a budget-blocked request."""
    _create_metrics()
    BUDGET_BLOCKED_TOTAL.labels(key_alias=key_alias).inc()


def update_budget(key_alias: str, spent_usd: float, remaining_usd: float) -> None:
    """Update budget gauges for a key."""
    _create_metrics()
    BUDGET_SPENT_USD.labels(key_alias=key_alias).set(spent_usd)
    BUDGET_REMAINING_USD.labels(key_alias=key_alias).set(remaining_usd)


def record_failover(capability: str, from_model: str, to_model: str) -> None:
    """Record a fallback chain invocation."""
    _create_metrics()
    FAILOVER_TOTAL.labels(
        capability=capability, from_model=from_model, to_model=to_model
    ).inc()


def start_metrics_server(port: int = 9090) -> None:
    """Start a Prometheus HTTP metrics server on the given port.

    Call this at gateway startup. Metrics will be available at http://<host>:9090/metrics
    """
    _create_metrics()
    start_http_server(port)
    UPTIME_SECONDS.set(time.time() - _start_time)


# ──────────────────────────────────────────────────────────────
# Quick CLI demo
# ──────────────────────────────────────────────────────────────

def main() -> None:
    import sys

    if Counter is None:
        print("prometheus_client not installed — cannot run demo")
        print("Install with: pip install prometheus_client")
        return

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9090
    start_metrics_server(port)

    # Simulate some metrics
    record_request("fast-json", "nemotron-3.5-lightning-30b-a3b", "nvidia", "200", 1.8)
    record_request("general", "gpt-oss-20b", "nvidia", "200", 9.9)
    record_rate_limit("marketdata")
    record_budget_block("marketdata")
    update_budget("marketdata", spent_usd=12.50, remaining_usd=7.50)
    record_failover("fast-json", "nemotron-3.5-lightning-30b-a3b", "gemma-4-31b-it")

    print(f"Prometheus metrics server started on port {port}")
    print("Visit http://localhost:{port}/metrics to see metrics".format(port=port))
    print("Press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped")


if __name__ == "__main__":
    main()
