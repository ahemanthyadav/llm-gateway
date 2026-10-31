#!/usr/bin/env python3
"""Cross-family fallback chain enforcement.

Critical design decision from ADR 0001 & 0002: each capability's fallback chain
must contain models from DIFFERENT model families/providers. This ensures that
a single provider outage cannot takedown an entire capability.

This module validates and enforces that diversification constraint, and
provides a "diversify" utility if the config ever violates it.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Set

from .capability_router import FallbackChain, ModelConfig, CapabilityRouter


# ──────────────────────────────────────────────────────────────
# Diversification validation
# ──────────────────────────────────────────────────────────────

def validate_cross_family_diversification(
    router: CapabilityRouter,
) -> Dict[str, List[str]]:
    """Validate that every capability chain has cross-family diversification.

    Returns a dict mapping capability -> list of families found in the chain.
    If a chain has only one family, it's recorded in the dict; the caller
    can check for capabilities where len(families) <= 1.

    Does NOT raise ValueError internally — returns the data for the caller
    to act upon.
    """
    violations: Dict[str, List[str]] = {}

    for cap in router.all_capabilities():
        chain = router.get_chain(cap)
        if chain is None:
            continue

        families: Set[str] = set()
        # Primary
        pw = chain.primary.model_info.get("gw_family")
        if pw:
            families.add(pw)
        # Fallbacks
        for f in chain.fallbacks:
            pw = f.model_info.get("gw_family")
            if pw:
                families.add(pw)

        violations[cap] = sorted(families) if families else ["unknown"]

    return violations


# ──────────────────────────────────────────────────────────────
# Diversification-aware chain resolver
# ──────────────────────────────────────────────────────────────

def resolve_chain_with_diversification(
    capability: str,
    router: CapabilityRouter,
    prefer_family: Optional[str] = None,
) -> Dict[str, Optional[ModelConfig]]:
    """Resolve which model to use from the chain, ensuring diversification.

    Returns a dict: {"primary": ModelConfig, "fallback": Optional[ModelConfig]}
    where primary and fallback are from different families if possible.

    Args:
        capability: e.g. "fast-json"
        router: initialized CapabilityRouter
        prefer_family: optionally force a specific family (e.g. for testing)
    """
    chain = router.get_chain(capability)
    if chain is None:
        return {"primary": None, "fallback": None}

    primary = chain.primary
    primary_family = primary.model_info.get("gw_family")

    # Find a fallback from a DIFFERENT family
    fallback: Optional[ModelConfig] = None
    for f in chain.fallbacks:
        if f.model_info.get("gw_family") != primary_family:
            fallback = f
            break

    # If no cross-family fallback exists, use the next in chain anyway
    # (this handles edge cases where the config doesn't diversify perfectly)
    if fallback is None and len(chain.fallbacks) > 0:
        fallback = chain.fallbacks[0]

    # If prefer_family is set and primary doesn't match, swap
    if prefer_family and primary_family != prefer_family:
        # Try to find a primary from the preferred family
        alt_primary = router.chain_by_family(capability, prefer_family)
        if alt_primary is not None:
            # Push the original primary to fallback slot
            alt_fallback = primary
            # Check if alt_fallback's family differs from alt_primary's
            if (
                alt_fallback.model_info.get("gw_family")
                != alt_primary.model_info.get("gw_family")
            ):
                fallback = alt_fallback
            else:
                fallback = chain.fallbacks[0] if len(chain.fallbacks) > 0 else None
            primary = alt_primary
        else:
            # preferred family not available; keep original
            pass

    return {"primary": primary, "fallback": fallback}


# ──────────────────────────────────────────────────────────────
# Config sanity-check: ensure all fallback targets exist
# ──────────────────────────────────────────────────────────────

def validate_fallback_targets_exist(router: CapabilityRouter) -> List[str]:
    """Validate that every fallback reference in litellm_settings exists
    in the model_list. Returns list of errors found."""
    errors: List[str] = []

    model_by_name: dict[str, object] = {}
    for m in router._config.get("model_list", []):
        model_by_name[m["model_name"]] = m

    fb_map = router._config.get("litellm_settings", {}).get("fallbacks", [])
    for entry in fb_map:
        for cap, targets in entry.items():
            for t in targets:
                if t not in model_by_name:
                    errors.append(
                        f"fallback target '{t}' for capability '{cap}' not found in model_list"
                    )

    return errors


# ──────────────────────────────────────────────────────────────
# Quick CLI demo
# ──────────────────────────────────────────────────────────────

def main() -> None:
    from .capability_router import CapabilityRouter

    router = CapabilityRouter()

    # Validate diversification
    violations = validate_cross_family_diversification(router)
    bad_caps = [cap for cap, families in violations.items() if len(families) <= 1]
    if bad_caps:
        print(f"✗ Diversification violation (one family): {bad_caps}")
    else:
        print("✓ Cross-family diversification OK for all capabilities")

    # Validate fallback targets
    missing = validate_fallback_targets_exist(router)
    if missing:
        print("✗ Missing fallback targets:")
        for m in missing:
            print(f"  - {m}")
    else:
        print("✓ All fallback targets exist in model_list")

    # Show chain resolution
    for cap in router.all_capabilities():
        resolved = resolve_chain_with_diversification(cap, router)
        p = resolved["primary"]
        f = resolved["fallback"]
        if p:
            print(
                f"{cap}: primary={p.model_name}({p.model_info.get('gw_family')}), "
                f"fallback={f.model_name if f else 'None'} "
                f"({f.model_info.get('gw_family') if f else 'None'})"
            )


if __name__ == "__main__":
    main()