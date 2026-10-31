#!/usr/bin/env python3
"""RPM (requests per minute) and budget enforcement for llm-gateway.

This module implements the two RPM-related constraints that make the gateway
safe to share across projects:

1. **Per-deployment RPM**: Each model in litellm.yaml has an `rpm` field. The
   sum of all NVIDIA deployments must be ≤ 30/min (headroom under the ~40/min
   free-tier account limit). Validated by `tests/test_config.py`.

2. **Per-key RPM limit**: Each project key has its own `rpm_limit` enforced at
   request time. If a key exceeds its limit, subsequent calls get 429.

3. **Per-project budget**: Each project key can have an optional USD budget
   tracked in the database. When spend exceeds the budget, behavior depends on
   configuration (soft limit vs hard stop).

This module provides in-memory tracking for single-replica deployments.
"""

from __future__ import annotations

import time
import yaml
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


# ──────────────────────────────────────────────────────────────
# NVIDIA Free-Tier RPM Budget
# ──────────────────────────────────────────────────────────────

NVIDIA_FREE_TIER_RPM_BUDGET = 30


class RpmBudgetTracker:
    """Tracks RPM consumption against the NVIDIA free-tier budget."""

    def __init__(self, config_path: str = "config/litellm.yaml") -> None:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        total = 0
        for m in config.get("model_list", []):
            model_str = m.get("litellm_params", {}).get("model", "")
            if model_str.startswith("nvidia_nim/"):
                rpm = m.get("litellm_params", {}).get("rpm", 0) or 0
                total += rpm
        self._total_rpm = total

    @property
    def total_rpm(self) -> int:
        """Total RPM across all NVIDIA deployments."""
        return self._total_rpm

    @property
    def deployment_rpm(self) -> Dict[str, int]:
        """Per-deployment RPM breakdown."""
        return {
            m["model_name"]: m["litellm_params"]["rpm"]
            for m in self._get_model_list()
            if m.get("litellm_params", {}).get("model", "").startswith("nvidia_nim/")
        }

    def _get_model_list(self) -> List[dict]:
        with open("config/litellm.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f).get("model_list", [])

    def check_budget(self, override_rpm: int = 0) -> Tuple[bool, str]:
        """Check if total RPM is within the free-tier budget.

        Returns (ok, message). If ok=False, message explains the violation.
        """
        effective = self._total_rpm + override_rpm
        if effective <= NVIDIA_FREE_TIER_RPM_BUDGET:
            return True, f"OK: {effective} ≤ {NVIDIA_FREE_TIER_RPM_BUDGET} RPM"
        else:
            return False, (
                f"FAIL: {effective} > {NVIDIA_FREE_TIER_RPM_BUDGET} RPM "
                f"(exceeds by {effective - NVIDIA_FREE_TIER_RPM_BUDGET})"
            )

    def rpm_headroom(self) -> int:
        """Return remaining RPM headroom."""
        return NVIDIA_FREE_TIER_RPM_BUDGET - self._total_rpm


class PerKeyRateLimiter:
    """Enforces per-project-key RPM limits with a sliding-window algorithm."""

    def __init__(self, rpm_limit: int) -> None:
        if rpm_limit <= 0:
            raise ValueError("rpm_limit must be > 0")
        self.rpm_limit = rpm_limit
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def _prune_window(self, key: str, now: float, window_sec: float = 60.0) -> None:
        lst = self._requests[key]
        cutoff = now - window_sec
        self._requests[key] = [t for t in lst if t > cutoff]

    def try_consume(self, key: str) -> Tuple[bool, float]:
        """Attempt to consume one RPM token for *key*.

        Returns (allowed, wait_seconds).
        - If allowed=True: proceed with the request; wait_seconds is how long
          until the next token will be available if you want to minimize wait.
        - If allowed=False: the key is rate-limited; wait_seconds is the
          minimum time to wait before retrying.
        """
        now = time.time()
        self._prune_window(key, now)
        lst = self._requests[key]
        if len(lst) < self.rpm_limit:
            lst.append(now)
            return True, 0.0
        oldest = min(lst)
        wait = 60.0 - (now - oldest)
        if wait < 0:
            wait = 0.0
        return False, max(wait, 0.0)

    def reset_key(self, key: str) -> None:
        """Reset a key's rate-limit window (e.g., for admin cleanup)."""
        self._requests[key].clear()


class PerKeyBudget:
    """Tracks per-project key spend against an optional USD budget."""

    def __init__(
        self,
        key_alias: str,
        max_budget_usd: Optional[float] = None,
        budget_duration: str = "30d",
    ) -> None:
        self.key_alias = key_alias
        self.max_budget_usd = max_budget_usd
        self.budget_duration = budget_duration
        self.spent_usd = 0.0
        self._start_time = time.time()

    @property
    def has_budget(self) -> bool:
        return self.max_budget_usd is not None and self.max_budget_usd > 0

    def record_spend(self, amount_usd: float) -> None:
        """Record USD spend for a completed request."""
        self.spent_usd += amount_usd

    def budget_exceeded(self) -> bool:
        """Return True if the budget has been exceeded."""
        if not self.has_budget:
            return False
        return self.spent_usd > self.max_budget_usd

    def reset(self) -> None:
        """Reset spend counter (e.g., at start of new budget period)."""
        self.spent_usd = 0.0
        self._start_time = time.time()