#!/usr/bin/env python3
"""LiteLLM configuration generation from the llm-gateway architecture.

This module maps the architectural components (capability router,
fallback chains, RPM budget, project keys) to the single source of truth:
config/litellm.yaml. It can generate a valid litellm.yaml from structured data,
useful for:

1. Administrative tooling (generate config from a database or UI)
2. Testing/validation (produce config for test_config.py to validate)
3. Documentation (show the complete config structure)
4. Bootstrap (initial setup before the git-tracked config exists)

The generated config mirrors the actual config/litellm.yaml format used by
LiteLLM 1.106.0, including:
- model_list with litellm_params, model_info (gw_* custom keys)
- litellm_settings with drop_params, retry/cooldown config
- router_settings with routing_strategy, allowed_fails, cooldown_time
- general_settings with master_key, database_url, store_model_in_db
"""

from __future__ import annotations

import json
import yaml
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .capability_router import CapabilityRouter, FallbackChain, ModelConfig


# ──────────────────────────────────────────────────────────────
# Data model for config generation
# ──────────────────────────────────────────────────────────────

@dataclass
class DeploymentRpmInfo:
    """RPM info for a single model deployment."""
    model_name: str
    model: str
    rpm: int
    timeout: int
    api_key_env: str
    extra_body: Optional[dict] = None
    input_type: Optional[str] = None


@dataclass
class CapabilityConfig:
    """Configuration for a single capability."""
    capability: str
    primary: DeploymentRpmInfo
    fallbacks: List[DeploymentRpmInfo]
    family: str
    provider: str
    cost: str


@dataclass
class GatewayConfig:
    """Complete gateway configuration to generate."""
    capabilities: List[CapabilityConfig]
    request_timeout: int = 240
    num_retries: int = 2
    routing_strategy: str = "simple-shuffle"
    allowed_fails: int = 3
    cooldown_time: int = 300
    master_key_env: str = "LITELLM_MASTER_KEY"
    database_url_env: str = "DATABASE_URL"
    store_model_in_db: bool = False
    disable_spend_logs: bool = False


# ──────────────────────────────────────────────────────────────
# LiteLLM config generator
# ──────────────────────────────────────────────────────────────

class LitellmConfigGenerator:
    """Generate a valid config/litellm.yaml from architectural data model."""""

    def __init__(self, config: GatewayConfig, router: CapabilityRouter) -> None:
        self.config = config
        self.router = router
        self.model_list: List[dict] = []
        self.fallbacks_config: List[dict] = []
        self._build()

    def _build(self) -> None:
        self._build_model_list()
        self._build_fallbacks()
        self._build_settings()

    def _build_model_list(self) -> None:
        used_names: set[str] = set()
        for cap_cfg in self.config.capabilities:
            primary = cap_cfg.primary
            if primary.model_name not in used_names:
                self._add_model(
                    model_name=primary.model_name,
                    model=primary.model,
                    rpm=primary.rpm,
                    timeout=primary.timeout,
                    api_key_env=primary.api_key_env,
                    extra_body=primary.extra_body,
                    input_type=primary.input_type,
                    model_info={"gw_family": cap_cfg.family,
                                "gw_provider": cap_cfg.provider,
                                "gw_cost": cap_cfg.cost},
                )
                used_names.add(primary.model_name)
            for fb in cap_cfg.fallbacks:
                if fb.model_name not in used_names:
                    self._add_model(
                        model_name=fb.model_name,
                        model=fb.model,
                        rpm=fb.rpm,
                        timeout=fb.timeout,
                        api_key_env=primary.api_key_env,
                        extra_body=fb.extra_body,
                        input_type=fb.input_type,
                        model_info={"gw_family": fb.family,
                                    "gw_provider": fb.provider,
                                    "gw_cost": fb.cost},
                    )
                    used_names.add(fb.model_name)

    def _add_model(self, **kwargs) -> None:
        self.model_list.append(kwargs)

    def _build_fallbacks(self) -> None:
        self.fallbacks_config = []
        for cap_cfg in self.config.capabilities:
            chain: List[dict] = []
            primary_info = {"model_name": cap_cfg.primary.model_name}
            chain.append(primary_info)
            for i, fb in enumerate(cap_cfg.fallbacks, start=2):
                chain.append({"model_name": fb.model_name})
            self.fallbacks_config.append({cap_cfg.capability: chain})

    def _build_settings(self) -> None:
        fallbacks = self.fallbacks_config
        self_ = {
            "drop_params": True,
            "request_timeout": self.config.request_timeout,
            "num_retries": self.config.num_retries,
            "fallbacks": fallbacks,
        }
        router_ = {
            "routing_strategy": self.config.routing_strategy,
            "allowed_fails": self.config.allowed_fails,
            "cooldown_time": self.config.cooldown_time,
        }
        general_ = {
            "master_key": f"os.environ/{self.config.master_key_env}",
            "database_url": f"os.environ/{self.config.database_url_env}",
            "store_model_in_db": self.config.store_model_in_db,
            "disable_spend_logs": self.config.disable_spend_logs,
        }
        self.full_config = {
            "model_list": self.model_list,
            "litellm_settings": self_,
            "router_settings": router_,
            "general_settings": general_,
        }

    def write(self, path: str = "config/litellm.yaml") -> None:
        import os
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.full_config, f, default_flow_style=False, sort_keys=False)
        print(f"✓ Config written to {path}")


# ──────────────────────────────────────────────────────────────
# Reference config generation
# ──────────────────────────────────────────────────────────────

# Reference model data matching the actual project config
REFERENCE_MODELS = [
    # fast-json chain
    ("fast-json", "nemotron-3.5-lightning-30b-a3b", "nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b",
     5, 60, "nemotron", "nvidia", "free",
     {"chat_template_kwargs": {"enable_thinking": False}}, None),

    ("fast-json.2", "gemma-4-31b-it", "nvidia_nim/google/gemma-4-31b-it",
     4, 60, "gemma", "nvidia", "free", None, None),

    ("fast-json.3", "gpt-oss-20b", "nvidia_nim/openai/gpt-oss-20b",
     3, 60, "gpt-oss", "nvidia", "free", None, None),

    # general chain
    ("general", "gpt-oss-20b", "nvidia_nim/openai/gpt-oss-20b",
     4, 90, "gpt-oss", "nvidia", "free", None, None),

    ("general.2", "gemma-4-31b-it", "nvidia_nim/google/gemma-4-31b-it",
     3, 90, "gemma", "nvidia", "free", None, None),

    # reasoning chain
    ("reasoning", "nemotron-3-super-120b-a12b", "nvidia_nim/nvidia/nemotron-3-super-120b-a12b",
     3, 180, "nemotron", "nvidia", "free", None, None),

    ("reasoning.2", "glm-5.3", "nvidia_nim/z-ai/glm-5.3",
     2, 180, "glm", "nvidia", "free", None, None),

    # long-context chain
    ("long-context", "glm-5.3", "nvidia_nim/z-ai/glm-5.3",
     2, 240, "glm", "nvidia", "free", None, "query"),

    ("long-context.2", "nemotron-3-super-120b-a12b", "nvidia_nim/nvidia/nemotron-3-super-120b-a12b",
     1, 240, "nemotron", "nvidia", "free", None, None),

    # embed chain
    ("embed", "nemotron-3-embed-1b", "nvidia_nim/nvidia/nemotron-3-embed-1b",
     2, 60, "nemotron-embed", "nvidia", "free", None, "query"),

    ("embed.2", "llama-nemotron-embed-vl-1b-v2", "nvidia_nim/nvidia/llama-nemotron-embed-vl-1b-v2",
     1, 60, "llama-nemotron-embed", "nvidia", "free", None, "query"),
]


def generate_reference_config(path: str = "config/litellm.yaml") -> None:
    """Generate the reference config/litellm.yaml from reference model data."""
    from arch.capability_router import CapabilityRouter

    # Group by capability
    caps_data: dict[str, List[dict]] = {}
    for (
        cap, model_name, model, rpm, timeout, family, provider, cost,
        extra_body, input_type
    ) in REFERENCE_MODELS:
        caps_data.setdefault(cap, []).append({
            "model_name": model_name,
            "model": model,
            "rpm": rpm,
            "timeout": timeout,
            "family": family,
            "provider": provider,
            "cost": cost,
            "extra_body": extra_body,
            "input_type": input_type,
        })

    # Build capability configs
    capability_configs: List = []
    for cap, models in caps_data.items():
        primary_data = models[0]
        fallbacks_data = models[1:]

        primary = DeploymentRpmInfo(
            model_name=primary_data["model_name"],
            model=primary_data["model"],
            rpm=primary_data["rpm"],
            timeout=primary_data["timeout"],
            api_key_env="NVIDIA_NIM_API_KEY",
            extra_body=primary_data.get("extra_body"),
            input_type=primary_data.get("input_type"),
        )

        fallbacks = []
        for fb_data in fallbacks_data:
            fallbacks.append(DeploymentRpmInfo(
                model_name=fb_data["model_name"],
                model=fb_data["model"],
                rpm=fb_data["rpm"],
                timeout=fb_data["timeout"],
                api_key_env="NVIDIA_NIM_API_KEY",
                extra_body=fb_data.get("extra_body"),
                input_type=fb_data.get("input_type"),
            ))

        cost = primary_data["cost"]
        family = primary_data["family"]
        provider = primary_data["provider"]

        class _CapabilityConfig:
            capability = cap
            primary = primary
            fallbacks = fallbacks
            family = family
            provider = provider
            cost = cost

        capability_configs.append(_CapabilityConfig())

    gw_config = GatewayConfig(
        capabilities=capability_configs,
        request_timeout=240,
        num_retries=2,
        routing_strategy="simple-shuffle",
        allowed_fails=3,
        cooldown_time=300,
        master_key_env="LITELLM_MASTER_KEY",
        database_url_env="DATABASE_URL",
        store_model_in_db=False,
        disable_spend_logs=False,
    )

    generator = LitellmConfigGenerator(gw_config, CapabilityRouter())
    generator.write(path)


# ──────────────────────────────────────────────────────────────
# Quick CLI demo
# ──────────────────────────────────────────────────────────────

def main() -> None:
    from arch.capability_router import CapabilityRouter
    import tempfile, os

    # Generate to temp file
    generate_reference_config("/tmp/test_litellm_gen.yaml")

    # Verify
    import yaml
    with open("/tmp/test_litellm_gen.yaml") as f:
        config = yaml.safe_load(f)

    print(f"Generated config model_list entries: {len(config.get('model_list', []))}")
    print(f"fallbacks sections: {len(config.get('litellm_settings', {}).get('fallbacks', []))}")
    print(f"router_settings: {config.get('router_settings')}")
    print(f"general_settings: {config.get('general_settings')}")

    # Validate against test_config.py
    print("\nRunning test_config.py...")
    import subprocess
    result = subprocess.run(
        ["python3", "tests/test_config.py"],
        cwd=os.path.dirname(__file__),
        capture_output=True, text=True,
    )
    print(f"  exit_code={result.returncode}")
    print(f"  {'PASS' if result.returncode == 0 else 'FAIL'}")
    if result.stdout:
        print(f"  output: {result.stdout[:200]}")
    if result.stderr:
        print(f"  errors: {result.stderr[:200]}")

    # Write to actual config path
    overwrite = input("\nWrite to config/litellm.yaml? [y/N]: ")
    if overwrite.lower() == "y":
        generator = LitellmConfigGenerator(
            # Minimal config for validation
            type("GC", (), {
                'capabilities': [],
                'request_timeout': 240,
                'num_retries': 2,
                'routing_strategy': 'simple-shuffle',
                'allowed_fails': 3,
                'cooldown_time': 300,
                'master_key_env': 'LITELLM_MASTER_KEY',
                'database_url_env': 'DATABASE_URL',
                'store_model_in_db': False,
                'disable_spend_logs': False,
            })(),
            CapabilityRouter(),
        )
        generator.write("config/litellm.yaml")
        print("✓ Config written to config/litellm.yaml")
    else:
        print("Config not overwritten")


if __name__ == "__main__":
    main()
