#!/usr/bin/env python3
"""Cost estimator CLI for llm-gateway.

Estimates whether a project key can afford N requests at a given priority,
using the provider model catalog and SmartSelector scoring.

Usage:
    python3 arch/cost_estimator.py --key marketdata --capability fast-json --requests 100 --priority cost
    python3 arch/cost_estimator.py --capability reasoning --requests 10 --priority quality
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

# Allow running as `python3 arch/cost_estimator.py` from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arch.provider_model import (
    CAPABILITY_PROVIDER_MAP,
    Provider,
    ProviderBudget,
    ProviderRateLimit,
    PROVIDER_MODELS,
    SmartSelector,
)


def estimate_cost(
    capability: str,
    num_requests: int,
    priority: str = "balanced",
    preferred_providers: Optional[list[Provider]] = None,
    avoided_providers: Optional[list[Provider]] = None,
    max_budget_usd: Optional[float] = None,
) -> dict:
    """Estimate total cost and feasibility for N requests.

    Returns a dict with:
      - selected_provider, selected_model, model_name
      - cost_per_request_usd, total_cost_usd
      - rpm_limit_per_min, requests_per_min_feasible
      - affordable (within budget), budget_remaining
      - reason
    """
    # Build per-provider rate limit + budget state
    rate_limits: dict[Provider, ProviderRateLimit] = {}
    budgets: dict[Provider, ProviderBudget] = {}

    for provider in PROVIDER_MODELS.keys():
        rate_limits[provider] = ProviderRateLimit(
            key_alias="estimator", provider=provider
        )
        budgets[provider] = ProviderBudget(
            key_alias="estimator",
            provider=provider,
            max_budget_usd=max_budget_usd or 0.0,
        )

    # Smart selection (single request model, then extrapolate)
    result = SmartSelector.select_model(
        capability=capability,
        preferred_providers=preferred_providers,
        avoided_providers=avoided_providers,
        key_rate_limits=rate_limits,
        key_budgets=budgets,
        task_priority=priority,
    )

    if result is None:
        return {
            "capability": capability,
            "num_requests": num_requests,
            "priority": priority,
            "affordable": False,
            "selected_provider": None,
            "selected_model": None,
            "model_name": None,
            "cost_per_request_usd": 0.0,
            "total_cost_usd": 0.0,
            "rpm_limit_per_min": 0,
            "requests_per_min_feasible": 0,
            "budget_remaining": max_budget_usd or 0.0,
            "reason": f"No available model for capability '{capability}' at priority '{priority}'",
        }

    provider, model = result

    # Cost per request (assume ~756 tokens: 500 input + 256 output)
    estimated_tokens = 756
    cost_per_request = (estimated_tokens / 1000) * model.cost_per_1k_tokens
    total_cost = cost_per_request * num_requests

    # RPM feasibility: how many requests can this model serve per minute?
    rpm_limit = model.rpm_limit
    requests_per_min_feasible = rpm_limit if rpm_limit > 0 else 0

    # Budget check
    affordable = True
    budget_remaining = 0.0
    if max_budget_usd is not None and max_budget_usd > 0:
        budget_remaining = max(0.0, max_budget_usd - total_cost)
        affordable = total_cost <= max_budget_usd

    return {
        "capability": capability,
        "num_requests": num_requests,
        "priority": priority,
        "affordable": affordable,
        "selected_provider": provider.name,
        "selected_model": model.display_name,
        "model_name": model.model_name,
        "cost_per_request_usd": round(cost_per_request, 6),
        "total_cost_usd": round(total_cost, 6),
        "rpm_limit_per_min": rpm_limit,
        "requests_per_min_feasible": requests_per_min_feasible,
        "budget_remaining_usd": round(budget_remaining, 6),
        "reason": f"{model.display_name} ({provider.name}) — {priority} priority",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate cost and feasibility for LLM requests via llm-gateway"
    )
    parser.add_argument("--key", default="estimator", help="project key alias (for display only)")
    parser.add_argument(
        "--capability", required=True,
        help="capability: fast-json, general, reasoning, long-context, embed",
    )
    parser.add_argument(
        "--requests", type=int, default=1,
        help="number of requests to estimate (default: 1)",
    )
    parser.add_argument(
        "--priority", default="balanced",
        choices=["cost", "speed", "quality", "balanced"],
        help="selection priority (default: balanced)",
    )
    parser.add_argument(
        "--max-budget-usd", type=float, default=None,
        help="optional max USD budget to check affordability against",
    )
    parser.add_argument(
        "--preferred-providers", default=None,
        help="comma-separated provider names to prefer (e.g. NVIDIA,GROQ)",
    )
    parser.add_argument(
        "--avoided-providers", default=None,
        help="comma-separated provider names to avoid",
    )
    parser.add_argument(
        "--json", action="store_true", help="output machine-readable JSON"
    )
    args = parser.parse_args()

    # Parse provider lists
    pref = None
    if args.preferred_providers:
        pref = [Provider[p.strip().upper()] for p in args.preferred_providers.split(",") if p.strip()]
    avoid = None
    if args.avoided_providers:
        avoid = [Provider[p.strip().upper()] for p in args.avoided_providers.split(",") if p.strip()]

    est = estimate_cost(
        capability=args.capability,
        num_requests=args.requests,
        priority=args.priority,
        preferred_providers=pref,
        avoided_providers=avoid,
        max_budget_usd=args.max_budget_usd,
    )

    if args.json:
        print(json.dumps(est, indent=2))
        return

    # Human-readable output
    print(f"=== Cost Estimate: {args.capability} ===")
    print(f"Key: {args.key}")
    print(f"Requests: {args.requests}")
    print(f"Priority: {args.priority}")
    print()

    if est["selected_provider"] is None:
        print(f"RESULT: UNAVAILABLE — {est['reason']}")
        sys.exit(1)

    print(f"Selected: {est['selected_model']} ({est['selected_provider']})")
    print(f"Model: {est['model_name']}")
    print(f"Reason: {est['reason']}")
    print()
    print(f"Cost per request: ${est['cost_per_request_usd']:.6f}")
    print(f"Total cost ({args.requests} requests): ${est['total_cost_usd']:.6f}")
    print(f"RPM limit (per min): {est['rpm_limit_per_min']}")
    print(f"Feasible requests/min: {est['requests_per_min_feasible']}")
    print()
    if est["max_budget_usd"] if "max_budget_usd" in est else args.max_budget_usd:
        print(f"Budget: ${args.max_budget_usd:.2f}")
        print(f"Remaining after {args.requests} requests: ${est['budget_remaining_usd']:.6f}")
        print(f"Affordable: {'YES' if est['affordable'] else 'NO — would exceed budget'}")


if __name__ == "__main__":
    main()
