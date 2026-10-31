#!/usr/bin/env python3
"""Budget enforcement middleware for llm-gateway.

Wraps LiteLLM completion/embedding calls with per-key budget checking:

- **Before** a request: check `PerKeyBudget.can_afford(estimated_cost)` → 402 if over budget
- **After** a request: `PerKeyBudget.record_spend(model_name, actual_cost)` from LiteLLM usage data

This module is framework-agnostic — it provides pure functions that can be
called from a LiteLLM callback, a middleware wrapper, or the admin UI.

Usage:
    from arch.budget_enforcer import BudgetEnforcer
    enforcer = BudgetEnforcer(key_alias="marketdata", max_budget_usd=20.0)

    # Before the call
    if not enforcer.can_proceed(estimated_cost_usd=0.05):
        raise BudgetExceededError("Budget exceeded")

    # After the call (from LiteLLM response usage)
    enforcer.record_actual_spend(model_name="nemotron-3.5-lightning-30b-a3b",
                                 cost_usd=0.03)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from arch.rpm_budget import PerKeyBudget


class BudgetExceededError(Exception):
    """Raised when a request would exceed the key's budget."""
    pass


@dataclass
class BudgetEnforcer:
    """Enforces per-key USD budget before and after LLM calls."""

    key_alias: str
    max_budget_usd: float
    budget_duration: str = "30d"
    _budget: PerKeyBudget = field(init=False)
    _enforced_count: int = 0
    _blocked_count: int = 0

    def __post_init__(self) -> None:
        self._budget = PerKeyBudget(
            key_alias=self.key_alias,
            max_budget_usd=self.max_budget_usd,
            budget_duration=self.budget_duration,
        )

    @property
    def spent_usd(self) -> float:
        return self._budget.spent_usd

    @property
    def remaining_usd(self) -> float:
        if self.max_budget_usd <= 0:
            return float("inf")
        return max(0.0, self.max_budget_usd - self._budget.spent_usd)

    @property
    def is_exceeded(self) -> bool:
        return self._budget.budget_exceeded()

    def can_proceed(self, estimated_cost_usd: float) -> bool:
        """Return True if the request can proceed within budget.

        If the estimated cost would push spend over budget, returns False
        and increments the blocked counter.
        """
        if self.max_budget_usd <= 0:
            # No budget limit — always allow
            self._enforced_count += 1
            return True

        if self._budget.can_afford(estimated_cost_usd):
            self._enforced_count += 1
            return True

        self._blocked_count += 1
        return False

    def require_proceed(self, estimated_cost_usd: float) -> None:
        """Like can_proceed(), but raises BudgetExceededError if blocked."""
        if not self.can_proceed(estimated_cost_usd):
            raise BudgetExceededError(
                f"Key '{self.key_alias}' budget exceeded: "
                f"${self.spent_usd:.4f} spent / ${self.max_budget_usd:.2f} limit. "
                f"Estimated cost ${estimated_cost_usd:.4f} would exceed budget."
            )

    def record_actual_spend(self, model_name: str, cost_usd: float) -> None:
        """Record actual spend from a completed LiteLLM response.

        Args:
            model_name: The model that served the request
            cost_usd: Actual USD cost (from LiteLLM response usage + model pricing)
        """
        self._budget.record_spend(model_name, cost_usd)

    def estimate_cost_usd(self, model_cost_per_1k: float,
                          input_tokens: int = 500,
                          output_tokens: int = 256) -> float:
        """Estimate USD cost for a request given token counts.

        Default assumes ~756 tokens (500 input + 256 output), matching
        SmartSelector's assumption in provider_model.py.
        """
        total_tokens = input_tokens + output_tokens
        return (total_tokens / 1000) * model_cost_per_1k

    def reset(self) -> None:
        """Reset spend counter (start of new budget period)."""
        self._budget.reset()

    def stats(self) -> dict:
        """Return enforcement statistics for observability."""
        return {
            "key_alias": self.key_alias,
            "max_budget_usd": self.max_budget_usd,
            "spent_usd": self.spent_usd,
            "remaining_usd": self.remaining_usd,
            "is_exceeded": self.is_exceeded,
            "enforced_count": self._enforced_count,
            "blocked_count": self._blocked_count,
        }


# ──────────────────────────────────────────────────────────────
# Quick CLI demo
# ──────────────────────────────────────────────────────────────

def main() -> None:
    import sys

    key_alias = sys.argv[1] if len(sys.argv) > 1 else "demo"
    max_budget = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0

    enforcer = BudgetEnforcer(key_alias=key_alias, max_budget_usd=max_budget)

    # Simulate a series of requests
    costs = [0.002, 0.003, 0.005, 0.01, 0.02, 0.05, 0.1, 0.5]
    for i, cost in enumerate(costs):
        if enforcer.can_proceed(cost):
            enforcer.record_actual_spend("demo-model", cost)
            print(f"Request {i+1}: allowed, cost=${cost:.4f}, "
                  f"spent=${enforcer.spent_usd:.4f}, remaining=${enforcer.remaining_usd:.4f}")
        else:
            print(f"Request {i+1}: BLOCKED, cost=${cost:.4f}, "
                  f"spent=${enforcer.spent_usd:.4f}, remaining=${enforcer.remaining_usd:.4f}")

    print(f"\nStats: {enforcer.stats()}")


if __name__ == "__main__":
    main()
