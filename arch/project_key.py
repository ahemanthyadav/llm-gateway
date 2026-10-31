#!/usr/bin/env python3
"""Per-project key scoping for llm-gateway.

This module implements the project key management that maps each project to:
- A set of allowed capabilities (e.g., "fast-json,general,embed")
- An RPM limit (requests per minute) for that key
- An optional USD budget (0 = free-tier only)
- A key alias for human readability

This mirrors the logic in ops/new-project.sh but as a Python module that
could be used by admin scripts, the admin UI, or the gateway itself.

Key storage format (as created by ops/new-project.sh and stored as
Secret <namespace>/llm-gateway-key):
  {
    "api-key": "<random-key-string>",
    "base-url": "http://llm-gateway.llm.svc.cluster.local:4000/v1",
    "capabilities": ["fast-json", "general", ...],
    "rpm_limit": 10,
    "max-budget-usd": 0,      # 0 = free only
    "budget-duration": "30d",
    "metadata": {"project": "marketdata"}
  }
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Set


# ──────────────────────────────────────────────────────────────
# Key generation
# ──────────────────────────────────────────────────────────────

def generate_project_key(
    key_length: int = 48,
    prefix: str = "sk-",
) -> str:
    """Generate a random API key for a project."""
    import secrets
    import string
    alphabet = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(key_length - len(prefix.rstrip("-"))))
    return prefix + random_part


# ──────────────────────────────────────────────────────────────
# Key config representation
# ──────────────────────────────────────────────────────────────

@dataclass
class ProjectKeyConfig:
    """Configuration for a project's API key."""

    key_alias: str
    api_key: str
    base_url: str
    capabilities: List[str]
    rpm_limit: int
    max_budget_usd: float
    budget_duration: str
    metadata: dict

    def to_dict(self) -> dict:
        return {
            "key_alias": self.key_alias,
            "api-key": self.api_key,
            "base-url": self.base_url,
            "capabilities": self.capabilities,
            "rpm_limit": self.rpm_limit,
            "max-budget-usd": self.max_budget_usd,
            "budget-duration": self.budget_duration,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: dict) -> "ProjectKeyConfig":
        return ProjectKeyConfig(
            key_alias=d["key_alias"],
            api_key=d["api-key"],
            base_url=d["base-url"],
            capabilities=d.get("capabilities", []),
            rpm_limit=d.get("rpm_limit", 10),
            max_budget_usd=d.get("max-budget-usd", 0),
            budget_duration=d.get("budget-duration", "30d"),
            metadata=d.get("metadata", {}),
        )


# ──────────────────────────────────────────────────────────────
# Key scoping validation
# ──────────────────────────────────────────────────────────────

class KeyScoper:
    """Validates that a project key only requests allowed capabilities and respects limits."""

    def __init__(self, router: "CapabilityRouter", key_config: ProjectKeyConfig) -> None:
        self.router = router
        self.key_config = key_config
        self._errors: List[str] = []
        self._validate()

    def _validate(self) -> None:
        """Run all validation checks on the key config."""
        valid_caps = set(self.router.all_capabilities())
        requested_caps: Set[str] = set(self.key_config.capabilities)
        invalid = requested_caps - valid_caps
        if invalid:
            self._errors.append(
                f"Key '{self.key_config.key_alias}': unknown capabilities {invalid}"
            )

        if self.key_config.rpm_limit <= 0:
            self._errors.append(
                f"Key '{self.key_config.key_alias}': rpm_limit must be > 0, got {self.key_config.rpm_limit}"
            )

        if self.key_config.max_budget_usd and self.key_config.max_budget_usd > 0:
            if self.key_config.budget_duration <= 0:
                self._errors.append(
                    f"Key '{self.key_config.key_alias}': budget set but duration <= 0"
                )

    @property
    def errors(self) -> List[str]:
        return self._errors

    def is_valid(self) -> bool:
        return len(self._errors) == 0


# ──────────────────────────────────────────────────────────────
# Key deployment helper
# ──────────────────────────────────────────────────────────────

def deploy_project_key(key_config: ProjectKeyConfig) -> dict:
    """Simulate the key deployment that ops/new-project.sh performs."""
    api_key = key_config.api_key or generate_project_key()

    key_obj = {
        "key_alias": key_config.key_alias,
        "key": api_key,
        "models": key_config.capabilities,
        "rpm_limit": key_config.rpm_limit,
        "metadata": {
            "project": key_config.key_alias,
            "max_budget_usd": key_config.max_budget_usd,
            "budget_duration": key_config.budget_duration,
        },
    }

    response = {
        "key": api_key,
        "key_alias": key_config.key_alias,
        "models": key_config.capabilities,
        "rpm_limit": key_config.rpm_limit,
    }

    return response


# ──────────────────────────────────────────────────────────────
# Quick CLI demo
# ──────────────────────────────────────────────────────────────

def main() -> None:
    from arch.capability_router import CapabilityRouter

    router = CapabilityRouter()

    key_config = ProjectKeyConfig(
        key_alias="marketdata",
        api_key="sk-test-abc123",
        base_url="http://llm-gateway.llm.svc.cluster.local:4000/v1",
        capabilities=["fast-json", "general", "embed"],
        rpm_limit=10,
        max_budget_usd=0,
        budget_duration="30d",
        metadata={"project": "marketdata", "namespace": "market-data"},
    )

    scoper = KeyScoper(router, key_config)
    print(f"Key '{key_config.key_alias}' validation:")
    if scoper.is_valid():
        print("  All capabilities valid, RPM limit OK")
    else:
        for e in scoper.errors:
            print(f"  ✗ {e}")

    print(f"\nAllowed capabilities and chain RPMs:")
    for cap in key_config.capabilities:
        chain_rpm = router.chain_rpm_total(cap)
        print(f"  {cap}: chain RPM={chain_rpm}")

    deployed = deploy_project_key(key_config)
    print(f"\nDeployed key alias: {deployed['key_alias']}")
    print(f"  Models: {deployed['models']}")
    print(f"  RPM limit: {deployed['rpm_limit']}")

    print("\n--- Invalid key example ---")
    bad_config = ProjectKeyConfig(
        key_alias="bad-project",
        api_key="sk-bad",
        base_url="http://example.com/v1",
        capabilities=["fast-json", "nonexistent-cap"],
        rpm_limit=5,
        max_budget_usd=0,
        budget_duration="30d",
        metadata={},
    )
    bad_scoper = KeyScoper(router, bad_config)
    print(f"Key '{bad_config.key_alias}' validation:")
    if bad_scoper.is_valid():
        print("  Valid")
    else:
        print("  Invalid (expected):")
        for e in bad_scoper.errors:
            print(f"    - {e}")


if __name__ == "__main__":
    main()