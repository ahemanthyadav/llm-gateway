#!/usr/bin/env python3
"""Core capability routing for llm-gateway.

Maps capability names (fast-json, general, reasoning, long-context, embed)
to ordered fallback chains of model configurations from different provider families.

This is the central routing table: clients never vendor model names — they ask
for a capability, and this module resolves the model chain with RPM limits,
timeouts, and provider metadata.
"""

from __future__ import annotations

import json
import yaml
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

# ──────────────────────────────────────────────────────────────
# Model configuration dataclass (mirrors litellm_params + model_info)
# ──────────────────────────────────────────────────────────────

@dataclass
class ModelConfig:
    model_name: str
    litellm_params: dict
    model_info: dict

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ModelConfig":
        return ModelConfig(
            model_name=d["model_name"],
            litellm_params=d["litellm_params"],
            model_info=d["model_info"],
        )


# ──────────────────────────────────────────────────────────────
# Fallback chain representation
# ──────────────────────────────────────────────────────────────

@dataclass
class FallbackChain:
    capability: str
    primary: ModelConfig
    fallbacks: List[ModelConfig]  # ordered by precedence

    def chain(self) -> List[ModelConfig]:
        """Return [primary, fallback1, fallback2, ...]"""
        return [self.primary, *self.fallbacks]

    def get_by_family(self, family: str) -> Optional[ModelConfig]:
        """Find a model in the chain by gw_family."""
        if self.primary.model_info.get("gw_family") == family:
            return self.primary
        for f in self.fallbacks:
            if f.model_info.get("gw_family") == family:
                return f
        return None

    def rpm_total(self) -> int:
        """Sum of RPM across all chain members."""
        total = self.primary.litellm_params.get("rpm", 0)
        for f in self.fallbacks:
            total += f.litellm_params.get("rpm", 0)
        return total


# ──────────────────────────────────────────────────────────────
# Capability router: builds chains from a litellm.yaml-like config
# ──────────────────────────────────────────────────────────────

class CapabilityRouter:
    """Resolves capability names to model chains with cross-family diversification."""

    def __init__(self, config_path: str = "config/litellm.yaml") -> None:
        self.config_path = config_path
        self._config = self._load_config(config_path)
        self._chains: Dict[str, FallbackChain] = {}
        self._build_chains()

    # ── config loading ─────────────────────────────────────────

    def _load_config(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _model_from_dict(self, m: dict) -> ModelConfig:
        return ModelConfig.from_dict(m)

    # ── chain building ─────────────────────────────────────────

    def _build_chains(self) -> None:
        """Build FallbackChain objects from config model_list + fallbacks."""

        model_list = self._config.get("model_list", [])
        # Index models by model_name
        by_name: dict[str, ModelConfig] = {}
        for m in model_list:
            cfg = self._model_from_dict(m)
            by_name[cfg.model_name] = cfg

        # Build fallback map: capability -> [primary, .2, .3, ...]
        fb_map = self._config.get("litellm_settings", {}).get("fallbacks", [])
        fallback_chains: dict[str, List[ModelConfig]] = {}

        for entry in fb_map:
            for cap, targets in entry.items():
                chain: List[ModelConfig] = []
                # Primary
                if cap in by_name:
                    chain.append(by_name[cap])
                # Fallbacks (ordered)
                for t in targets:
                    if t in by_name:
                        chain.append(by_name[t])
                fallback_chains.setdefault(cap, []).extend(chain)

        # Deduplicate while preserving order
        for cap in fallback_chains:
            seen = set()
            ordered = []
            for m in fallback_chains[cap]:
                if m.model_name not in seen:
                    seen.add(m.model_name)
                    ordered.append(m)
            fallback_chains[cap] = ordered

        # Wrap in FallbackChain with diversification info
        self._chains = {}
        for cap, members in fallback_chains.items():
            if not members:
                continue
            primary = members[0]
            fallbacks = members[1:]
            self._chains[cap] = FallbackChain(
                capability=cap,
                primary=primary,
                fallbacks=fallbacks,
            )

    # ── public API ──────────────────────────────────────────────

    def get_chain(self, capability: str) -> Optional[FallbackChain]:
        """Get the fallback chain for a capability."""
        return self._chains.get(capability)

    def all_capabilities(self) -> List[str]:
        """Return list of registered capability names."""
        return list(self._chains.keys())

    def chain_rpm_total(self, capability: str) -> int:
        """Total RPM across the entire fallback chain."""
        chain = self.get_chain(capability)
        if chain is None:
            return 0
        return chain.rpm_total()

    def chain_by_family(self, capability: str, family: str) -> Optional[ModelConfig]:
        """Find a model in the chain by gw_family (for diversification)."""
        chain = self.get_chain(capability)
        if chain is None:
            return None
        # Check primary
        if chain.primary.model_info.get("gw_family") == family:
            return chain.primary
        # Check fallbacks
        for f in chain.fallbacks:
            if f.model_info.get("gw_family") == family:
                return f
        return None

    def list_chains(self) -> List[dict]:
        """Human-readable listing of all capability chains."""
        result = []
        for cap in sorted(self._chains.keys()):
            ch = self._chains[cap]
            primary_info = {
                "model": ch.primary.model_name,
                "family": ch.primary.model_info.get("gw_family"),
                "provider": ch.primary.model_info.get("gw_provider"),
                "rpm": ch.primary.litellm_params.get("rpm"),
            }
            fallback_infos = [
                {
                    "model": f.model_name,
                    "family": f.model_info.get("gw_family"),
                    "provider": f.model_info.get("gw_provider"),
                    "rpm": f.litellm_params.get("rpm"),
                }
                for f in ch.fallbacks
            ]
            result.append(
                {
                    "capability": cap,
                    "primary": primary_info,
                    "fallbacks": fallback_infos,
                    "total_rpm": ch.rpm_total(),
                }
            )
        return result


# ──────────────────────────────────────────────────────────────
# Quick CLI demo
# ──────────────────────────────────────────────────────────────

def main() -> None:
    router = CapabilityRouter()
    for summary in router.list_chains():
        cap = summary["capability"]
        p = summary["primary"]
        print(
            f"{cap}: {p['model']} ({p['family']}/{p['provider']}) "
            f"+{len(summary['fallbacks'])} fallbacks, "
            f"total RPM={summary['total_rpm']}"
        )


if __name__ == "__main__":
    main()