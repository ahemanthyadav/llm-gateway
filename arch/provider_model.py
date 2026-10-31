#!/usr/bin/env python3
"""Provider model for llm-gateway multi-provider support.

Defines each AI provider's model catalog, rate limits, capabilities,
cost structure, and provider-specific metadata. This enables capability-aware
model selection across NVIDIA, Google Gemini, Groq Cloud, Cloudflare Workers AI,
from arch.capability_router import CapabilityRouter
GitHub Models, and Cerebras Inference.

Key design principles:
- Provider-agnostic capability routing (clients still ask for capabilities, not model names)
- Per-provider rate limit tracking and enforcement
- Cost-aware model selection based on budget consumption
- Cross-provider fallback chains for resilience
- Backward compatible: existing NVIDIA-only config still works
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field

from arch.capability_router import CapabilityRouter
from arch.rpm_budget import RpmBudgetTracker


# ──────────────────────────────────────────────────────────────
# Provider Enum
# ──────────────────────────────────────────────────────────────

class Provider(Enum):
    """AI provider identifiers."""
    NVIDIA = auto()       # NVIDIA NIM, free tier ~30 RPM account-wide
    GOOGLE_GEMINI = auto() # Google Gemini API
    GROQ = auto()         # Groq Cloud (fast inference)
    CLOUDFLARE_WORKERS_AI = auto()  # Cloudflare Workers AI
    GITHUB_MODELS = auto()   # GitHub Models (model garden)
    CEREBRAS = auto()      # Cerebras Inference (high-speed)
    OPENAI = auto()        # OpenAI (for compatibility layer)
    ANTHROPIC = auto()     # Anthropic Claude
    OPENROUTER = auto()    # OpenRouter (model aggregator, many models one key)
    OLLAMA = auto()        # Ollama (self-hosted local models)


# ──────────────────────────────────────────────────────────────
# Provider-specific model metadata
# ──────────────────────────────────────────────────────────────

@dataclass
class ProviderModelInfo:
    """Metadata for a model from a specific provider."""
    model_name: str          # The model identifier used in API calls
    display_name: str        # Human-readable name
    capabilities: Set[str]   # Which capabilities this model supports
    provider: Provider       # The provider enum
    cost_per_1k_tokens: float  # USD cost per 1k tokens (0 = free)
    max_output_tokens: int   # Maximum output tokens
    context_window: int      # Context window size (tokens)
    rpm_limit: int           # Rate limit per minute per key/accout
    tpms_limit: Optional[int] = None  # Tokens per minute (if different from RPM)
    input_type_required: Optional[str] = None  # e.g. "query" for asymmetric embedders
    description: str = ""    # Optional description
    notes: str = ""          # Optional notes (quirks, known issues)


# ──────────────────────────────────────────────────────────────
# Populate provider models catalog
# ──────────────────────────────────────────────────────────────

# Reference models from the existing project (NVIDIA) plus new providers
# These are representative models - actual availability would be verified
# via key probing at deployment time.

PROVIDER_MODELS: Dict[Provider, List[ProviderModelInfo]] = {
    # === NVIDIA (existing) ===
    Provider.NVIDIA: [
        ProviderModelInfo(
            model_name="nemotron-3.5-lightning-30b-a3b",
            display_name="nemotron-3.5-lightning-30b-a3b",
            capabilities={"fast-json", "general", "reasoning"},
            provider=Provider.NVIDIA,
            cost_per_1k_tokens=0.0,
            max_output_tokens=4096,
            context_window=8192,
            rpm_limit=5,  # per deployment
            tpms_limit=None,
            description="NVIDIA Nemotron 3.5 30B, thinking off for fast-json",
        ),
        ProviderModelInfo(
            model_name="gemma-4-31b-it",
            display_name="gemma-4-31b-it",
            capabilities={"fast-json", "general"},
            provider=Provider.NVIDIA,
            cost_per_1k_tokens=0.0,
            max_output_tokens=8192,
            context_window=8192,
            rpm_limit=4,
            tpms_limit=None,
            description="Google Gemma 4 31B via NVIDIA NIM, good for structured output",
        ),
        ProviderModelInfo(
            model_name="gpt-oss-20b",
            display_name="gpt-oss-20b",
            capabilities={"fast-json", "general", "embed"},
            provider=Provider.NVIDIA,
            cost_per_1k_tokens=0.0,
            max_output_tokens=4096,
            context_window=8192,
            rpm_limit=3,
            tpms_limit=None,
            description="OpenAI GPT-OSS 20B via NVIDIA NIM",
        ),
        ProviderModelInfo(
            model_name="nemotron-3-super-120b-a12b",
            display_name="nemotron-3-super-120b-a12b",
            capabilities={"reasoning", "long-context"},
            provider=Provider.NVIDIA,
            cost_per_1k_tokens=0.0,
            max_output_tokens=8192,
            context_window=131072,
            rpm_limit=3,
            tpms_limit=None,
            description="NVIDIA Nemotron 3 Super 120B for reasoning/long-context",
        ),
        ProviderModelInfo(
            model_name="nemotron-3-embed-1b",
            display_name="nemotron-3-embed-1b",
            capabilities={"embed"},
            provider=Provider.NVIDIA,
            cost_per_1k_tokens=0.0,
            max_output_tokens=8192,
            context_window=8192,
            rpm_limit=2,
            tpms_limit=None,
            input_type_required="query",  # NVIDIA asymmetric embedders need input_type
            description="NVIDIA Nemotron 3 embed 1B, asymmetric: input_type=query",
        ),
        ProviderModelInfo(
            model_name="llama-nemotron-embed-vl-1b-v2",
            display_name="llama-nemotron-embed-vl-1b-v2",
            capabilities={"embed"},
            provider=Provider.NVIDIA,
            cost_per_1k_tokens=0.0,
            max_output_tokens=8192,
            context_window=8192,
            rpm_limit=1,
            tpms_limit=None,
            input_type_required="query",
            description="NVIDIA LlamaNemotron embed VL 1B V2, multimodal embedder",
        ),
    ],
    # === Google Gemini ===
    Provider.GOOGLE_GEMINI: [
        ProviderModelInfo(
            model_name="gemini-1.5-flash",
            display_name="gemini-1.5-flash",
            capabilities={"general", "fast-json"},
            provider=Provider.GOOGLE_GEMINI,
            cost_per_1k_tokens=0.00015,  # $0.15 per 1M tokens input, $0.60 output
            max_output_tokens=8192,
            context_window=1_048_576,  # 1M tokens
            rpm_limit=1000,  # generous Gemini free/tiered limits
            tpms_limit=None,
            description="Google Gemini 1.5 Flash, fast and cost-effective",
        ),
        ProviderModelInfo(
            model_name="gemini-1.5-flash-8b",
            display_name="gemini-1.5-flash-8b",
            capabilities={"general", "fast-json"},
            provider=Provider.GOOGLE_GEMINI,
            cost_per_1k_tokens=0.000075,
            max_output_tokens=8192,
            context_window=1_048_576,
            rpm_limit=1000,
            tpms_limit=None,
            description="Google Gemini 1.5 Flash 8B, even faster/cheaper",
        ),
        ProviderModelInfo(
            model_name="gemini-1.5-pro",
            display_name="gemini-1.5-pro",
            capabilities={"reasoning", "general", "fast-json"},
            provider=Provider.GOOGLE_GEMINI,
            cost_per_1k_tokens=0.000375,
            max_output_tokens=8192,
            context_window=1_048_576,
            rpm_limit=2000,
            tpms_limit=None,
            description="Google Gemini 1.5 Pro, higher quality than Flash",
        ),
    ],
    # === Groq Cloud ===
    Provider.GROQ: [
        ProviderModelInfo(
            model_name="mixtral-8x7b-32768",
            display_name="mixtral-8x7b-32768",
            capabilities={"general", "fast-json"},
            provider=Provider.GROQ,
            cost_per_1k_tokens=0.00008,  # $0.08 per 1M tokens input
            max_output_tokens=8192,
            context_window=32768,
            rpm_limit=300,  # Groq's generous limits
            tpms_limit=None,
            description="Groq Mixtral 8x7B 32K context, fast inference",
        ),
        ProviderModelInfo(
            model_name="llama3-8b-8192",
            display_name="llama3-8b-8192",
            capabilities={"general", "fast-json"},
            provider=Provider.GROQ,
            cost_per_1k_tokens=0.00005,
            max_output_tokens=8192,
            context_window=8192,
            rpm_limit=500,
            tpms_limit=None,
            description="Groq Llama 3 8B 8K context",
        ),
        ProviderModelInfo(
            model_name="gemma-7b-it",
            display_name="gemma-7b-it",
            capabilities={"general", "fast-json"},
            provider=Provider.GROQ,
            cost_per_1k_tokens=0.00004,
            max_output_tokens=8192,
            context_window=8192,
            rpm_limit=500,
            tpms_limit=None,
            description="Groq Gemma 7B IT, instruction-tuned",
        ),
    ],
    # === Cloudflare Workers AI ===
    Provider.CLOUDFLARE_WORKERS_AI: [
        ProviderModelInfo(
            model_name="meta-llama/Llama-3.2-11B-Vision-Instruct",
            display_name="Llama-3.2-11B-Vision-Instruct",
            capabilities={"general", "fast-json"},
            provider=Provider.CLOUDFLARE_WORKERS_AI,
            cost_per_1k_tokens=0.0005,  # approximate per 1k tokens
            max_output_tokens=4096,
            context_window=131072,
            rpm_limit=100,  # Workers AI limits
            tpms_limit=None,
            description="Llama 3.2 11B Vision via Workers AI, multimodal",
        ),
        ProviderModelInfo(
            model_name="meta-llama/Llama-3.1-8B-Instruct",
            display_name="Llama-3.1-8B-Instruct",
            capabilities={"general", "fast-json"},
            provider=Provider.CLOUDFLARE_WORKERS_AI,
            cost_per_1k_tokens=0.0004,
            max_output_tokens=4096,
            context_window=131072,
            rpm_limit=200,
            tpms_limit=None,
            description="Llama 3.1 8B Instruct via Workers AI",
        ),
    ],
    # === GitHub Models ===
    Provider.GITHUB_MODELS: [
        ProviderModelInfo(
            model_name="meta-llama/Llama-3.1-8B-Instruct",
            display_name="Llama-3.1-8B-Instruct (GitHub)",
            capabilities={"general", "fast-json"},
            provider=Provider.GITHUB_MODELS,
            cost_per_1k_tokens=0.00055,  # GitHub pricing
            max_output_tokens=4096,
            context_window=128000,
            rpm_limit=5000,  # GitHub generous limits
            tpms_limit=None,
            description="Llama 3.1 8B Instruct via GitHub Models",
        ),
        ProviderModelInfo(
            model_name="meta-llama/Llama-3.2-11B-Vision-Instruct",
            display_name="Llama-3.2-11B-Vision-Instruct (GitHub)",
            capabilities={"general", "fast-json"},
            provider=Provider.GITHUB_MODELS,
            cost_per_1k_tokens=0.0006,
            max_output_tokens=4096,
            context_window=128000,
            rpm_limit=5000,
            tpms_limit=None,
            description="Llama 3.2 11B Vision via GitHub Models",
        ),
    ],
    # === OpenAI ===
    Provider.OPENAI: [
        ProviderModelInfo(
            model_name="gpt-4o-mini",
            display_name="GPT-4o Mini (OpenAI)",
            capabilities={"fast-json", "general", "reasoning"},
            provider=Provider.OPENAI,
            cost_per_1k_tokens=0.00015,  # $0.15 per 1M input, $0.60 output
            max_output_tokens=16384,
            context_window=128000,
            rpm_limit=500,  # OpenAI tier-dependent
            tpms_limit=None,
            description="OpenAI GPT-4o Mini, fast and cost-effective",
        ),
        ProviderModelInfo(
            model_name="gpt-4o",
            display_name="GPT-4o (OpenAI)",
            capabilities={"reasoning", "general", "fast-json", "long-context"},
            provider=Provider.OPENAI,
            cost_per_1k_tokens=0.0025,  # $2.50 per 1M input, $10 output
            max_output_tokens=16384,
            context_window=128000,
            rpm_limit=200,
            tpms_limit=None,
            description="OpenAI GPT-4o, high-quality reasoning",
        ),
    ],
    # === Anthropic ===
    Provider.ANTHROPIC: [
        ProviderModelInfo(
            model_name="claude-3-haiku",
            display_name="Claude 3 Haiku (Anthropic)",
            capabilities={"fast-json", "general"},
            provider=Provider.ANTHROPIC,
            cost_per_1k_tokens=0.00025,  # $0.25 per 1M input, $1.25 output
            max_output_tokens=4096,
            context_window=200000,
            rpm_limit=1000,
            tpms_limit=None,
            description="Anthropic Claude 3 Haiku, fast and compact",
        ),
        ProviderModelInfo(
            model_name="claude-3-sonnet",
            display_name="Claude 3 Sonnet (Anthropic)",
            capabilities={"reasoning", "general", "fast-json"},
            provider=Provider.ANTHROPIC,
            cost_per_1k_tokens=0.003,  # $3 per 1M input, $15 output
            max_output_tokens=8192,
            context_window=200000,
            rpm_limit=500,
            tpms_limit=None,
            description="Anthropic Claude 3 Sonnet, balanced reasoning",
        ),
    ],
    # === OpenRouter ===
    Provider.OPENROUTER: [
        ProviderModelInfo(
            model_name="openrouter/meta-llama/llama-3.1-8b-instruct",
            display_name="Llama 3.1 8B Instruct (OpenRouter)",
            capabilities={"fast-json", "general"},
            provider=Provider.OPENROUTER,
            cost_per_1k_tokens=0.0001,  # varies by model
            max_output_tokens=8192,
            context_window=128000,
            rpm_limit=1000,
            tpms_limit=None,
            description="OpenRouter — Llama 3.1 8B, aggregated pricing",
        ),
        ProviderModelInfo(
            model_name="openrouter/mistralai/mistral-7b-instruct",
            display_name="Mistral 7B Instruct (OpenRouter)",
            capabilities={"fast-json", "general"},
            provider=Provider.OPENROUTER,
            cost_per_1k_tokens=0.00007,
            max_output_tokens=8192,
            context_window=32768,
            rpm_limit=1000,
            tpms_limit=None,
            description="OpenRouter — Mistral 7B, low cost",
        ),
        ProviderModelInfo(
            model_name="openrouter/anthropic/claude-3-haiku",
            display_name="Claude 3 Haiku (OpenRouter)",
            capabilities={"fast-json", "general"},
            provider=Provider.OPENROUTER,
            cost_per_1k_tokens=0.00025,
            max_output_tokens=4096,
            context_window=200000,
            rpm_limit=1000,
            tpms_limit=None,
            description="OpenRouter — Claude 3 Haiku via aggregator",
        ),
    ],
    # === Ollama ===
    Provider.OLLAMA: [
        ProviderModelInfo(
            model_name="ollama/llama3.2",
            display_name="Llama 3.2 (Ollama)",
            capabilities={"fast-json", "general"},
            provider=Provider.OLLAMA,
            cost_per_1k_tokens=0.0,  # self-hosted, no API cost
            max_output_tokens=4096,
            context_window=128000,
            rpm_limit=10000,  # limited by local hardware, not provider
            tpms_limit=None,
            description="Ollama — self-hosted Llama 3.2, zero API cost",
        ),
        ProviderModelInfo(
            model_name="ollama/llama3.1",
            display_name="Llama 3.1 (Ollama)",
            capabilities={"general", "reasoning"},
            provider=Provider.OLLAMA,
            cost_per_1k_tokens=0.0,  # self-hosted
            max_output_tokens=8192,
            context_window=128000,
            rpm_limit=10000,
            tpms_limit=None,
            description="Ollama — self-hosted Llama 3.1, zero API cost",
        ),
    ],
    # === Cerebras Inference ===
    Provider.CEREBRAS: [
        ProviderModelInfo(
            model_name="nerrrmmLlama-3.1-8B-Instruct",
            display_name="Llama-3.1-8B-Instruct (Cerebras)",
            capabilities={"general", "fast-json"},
            provider=Provider.CEREBRAS,
            cost_per_1k_tokens=0.0001,  # Cerebras very fast/cheap approximate
            max_output_tokens=8192,
            context_window=131072,
            rpm_limit=1000,  # Cerebras high-speed inference
            tpms_limit=50000,  # tokens per minute is a key metric for Cerebras
            description="Cerebras Llama 3.1 8B, extreme speed via Wafer-Scale Engine",
        ),
        ProviderModelInfo(
            model_name="neroLlama-3.1-70B-Instruct",
            display_name="Llama-3.1-70B-Instruct (Cerebras)",
            capabilities={"reasoning", "general", "fast-json"},
            provider=Provider.CEREBRAS,
            cost_per_1k_tokens=0.0002,
            max_output_tokens=8192,
            context_window=131072,
            rpm_limit=200,
            tpms_limit=100000,
            description="Cerebras Llama 3.1 70B, high-capacity inference",
        ),
    ],
}


# ──────────────────────────────────────────────────────────────
# Capability-to-provider mapping
# ──────────────────────────────────────────────────────────────

# Which providers support which capabilities
CAPABILITY_PROVIDER_MAP: Dict[str, Set[Provider]] = {
    "fast-json": {
        Provider.NVIDIA,
        Provider.GOOGLE_GEMINI,
        Provider.GROQ,
        Provider.CLOUDFLARE_WORKERS_AI,
        Provider.GITHUB_MODELS,
        Provider.OPENAI,
        Provider.ANTHROPIC,
        Provider.OPENROUTER,
        Provider.OLLAMA,
    },
    "general": {
        Provider.NVIDIA,
        Provider.GOOGLE_GEMINI,
        Provider.GROQ,
        Provider.CLOUDFLARE_WORKERS_AI,
        Provider.GITHUB_MODELS,
        Provider.CEREBRAS,
        Provider.OPENAI,
        Provider.ANTHROPIC,
        Provider.OPENROUTER,
        Provider.OLLAMA,
    },
    "reasoning": {
        Provider.NVIDIA,
        Provider.GOOGLE_GEMINI,
        Provider.CEREBRAS,
        Provider.OPENAI,
        Provider.ANTHROPIC,
        Provider.OPENROUTER,
        Provider.OLLAMA,
    },
    "long-context": {
        Provider.NVIDIA,
        Provider.GOOGLE_GEMINI,
        Provider.OPENAI,
        Provider.OPENROUTER,
    },
    "embed": {
        Provider.NVIDIA,
        # Embedding providers would be added here
    },
}


# ──────────────────────────────────────────────────────────────
# Provider Rate Limit Tracker
# ──────────────────────────────────────────────────────────────

@dataclass
class ProviderRateLimit:
    """Tracks rate limit state for a specific provider+key combination."""
    key_alias: str
    provider: Provider
    rpm_consumed: int = 0
    rpm_reset_time: float = 0.0  # timestamp when RPM window resets
    tpms_consumed: int = 0
    tpms_reset_time: float = 0.0

    def remaining_rpm(self, rpm_limit: int) -> int:
        """Return remaining RPM for this provider+key."""
        return max(0, rpm_limit - self.rpm_consumed)

    def remaining_tpms(self, tpms_limit: int) -> int:
        """Return remaining TPMS for this provider+key."""
        if tpms_limit is None:
            return 999999  # effectively unlimited
        return max(0, tpms_limit - self.tpms_consumed)

    def can_make_request(self, rpm_limit: int, tpms_limit: Optional[int]) -> bool:
        """Check if a request can be made within rate limits."""
        return (self.rpm_consumed < rpm_limit and
                (tpms_limit is None or self.tpms_consumed < tpms_limit))

    def record_request(self, tokens_used: int = 0, rpm_increment: int = 1) -> None:
        """Record a request's consumption."""
        self.rpm_consumed += rpm_increment
        self.tpms_consumed += tokens_used

    def reset_if_needed(self, now: float) -> None:
        """Reset counters if the RPM window has expired."""
        if now >= self.rpm_reset_time:
            self.rpm_consumed = 0
            self.rpm_reset_time = now + 60.0  # 1-minute window
        if tpms_limit := self.tpms_reset_time and now >= self.tpms_reset_time:
            self.tpms_consumed = 0
            self.tpms_reset_time = now + 60.0


# ──────────────────────────────────────────────────────────────
# Per-key provider budget tracking
# ──────────────────────────────────────────────────────────────

@dataclass
class ProviderBudget:
    """Tracks spend per provider per key."""
    key_alias: str
    provider: Provider
    spent_usd: float = 0.0
    max_budget_usd: float = 0.0  # 0 = no limit
    budget_duration: str = "30d"
    # Per-model cost tracking
    cost_by_model: Dict[str, float] = field(default_factory=dict)

    def can_afford(self, estimated_cost_usd: float) -> bool:
        """Check if the key can afford this request."""
        if self.max_budget_usd <= 0:
            return True  # no budget limit
        return (self.spent_usd + estimated_cost_usd) <= self.max_budget_usd

    def record_spend(self, model_name: str, cost_usd: float) -> None:
        """Record spend for a completed request."""
        self.spent_usd += cost_usd
        self.cost_by_model[model_name] = self.cost_by_model.get(model_name, 0.0) + cost_usd

    def reset(self) -> None:
        """Reset budget (e.g., at start of new period)."""
        self.spent_usd = 0.0
        self.cost_by_model.clear()


# ──────────────────────────────────────────────────────────────
# Smart model selection logic
# ──────────────────────────────────────────────────────────────

class SmartSelector:
    """Selects the best provider/model based on multiple criteria."""

    @staticmethod
    def select_model(
        capability: str,
        preferred_providers: List[Provider] = None,
        avoided_providers: List[Provider] = None,
        key_rate_limits: Dict[Provider, ProviderRateLimit] = None,
        key_budgets: Dict[Provider, ProviderBudget] = None,
        task_priority: str = "balanced",  # "cost", "speed", "quality", "balanced"
    ) -> Optional[Tuple[Provider, ProviderModelInfo]]:
        """Select the best provider/model for a given capability.

        Args:
            capability: The requested capability (fast-json, general, etc.)
            preferred_providers: Order of preference (left = preferred)
            avoided_providers: Providers to avoid
            key_rate_limits: Per-key per-provider rate limit trackers
            key_budgets: Per-key per-provider budget trackers
            task_priority: cost | speed | quality | balanced

        Returns:
            Tuple of (Provider, ProviderModelInfo) or None if no suitable model
        """

        # Get candidate providers for this capability
        candidate_providers = CAPABILITY_PROVIDER_MAP.get(capability, set())

        if not candidate_providers:
            return None

        # Only consider providers that have rate limit and budget state
        if key_rate_limits:
            candidate_providers = candidate_providers & set(key_rate_limits.keys())
        if key_budgets:
            candidate_providers = candidate_providers & set(key_budgets.keys())

        if not candidate_providers:
            return None

        # Filter by preferences
        if preferred_providers:
            # Keep only preferred providers that also support the capability
            preferred_set = set(preferred_providers)
            candidate_providers = candidate_providers & preferred_set

        if avoided_providers:
            candidate_providers = candidate_providers - set(avoided_providers)

        if not candidate_providers:
            return None

        # Score each provider's best model
        scored: List[Tuple[float, Provider, ProviderModelInfo]] = []

        for provider in candidate_providers:
            models = PROVIDER_MODELS.get(provider, [])
            # Filter models that support this capability
            capable_models = [
                m for m in models if capability in m.capabilities
            ]

            if not capable_models:
                continue

            for model in capable_models:
                score = SmartSelector._score_model(
                    model, provider, task_priority,
                    key_rate_limits.get(provider) if key_rate_limits else None,
                    key_budgets.get(provider) if key_budgets else None,
                )
                if score is not None:
                    scored.append((score, provider, model))

        if not scored:
            return None

        # Sort by score (lower = better for cost, appropriate for other priorities)
        scored.sort(key=lambda x: x[0])
        best_score, best_provider, best_model = scored[0]
        return best_provider, best_model

    @staticmethod
    def _score_model(
        model: ProviderModelInfo,
        provider: Provider,
        task_priority: str,
        rate_limit: ProviderRateLimit = None,
        budget: ProviderBudget = None,
    ) -> Optional[float]:
        """Score a model based on priority and constraints.

        Returns a float score (lower is better), or None if the model is ineligible.
        """
        # Check rate limits
        if rate_limit and not rate_limit.can_make_request(
            model.rpm_limit, model.tpms_limit
        ):
            return None  # rate limit would be exceeded

        # Check budget
        if budget:
            # Estimate cost based on typical token usage
            # Assume ~500 input + 256 output tokens for typical request
            estimated_tokens = 756
            estimated_cost = (estimated_tokens / 1000) * model.cost_per_1k_tokens
            if not budget.can_afford(estimated_cost):
                return None  # would exceed budget

        # Score based on task priority
        if task_priority == "cost":
            # Lower cost is better
            return model.cost_per_1k_tokens
        elif task_priority == "speed":
            # Higher RPM limit = potentially faster (but not direct latency)
            # Use -rpm_limit so higher RPM gets lower (better) score
            if model.rpm_limit > 0:
                return -model.rpm_limit
            return 999999  # poor score if no RPM limit
        elif task_priority == "quality":
            # Prefer larger context windows and higher-capability models
            # Simple heuristic: context_window / cost_per_1k_tokens
            if model.cost_per_1k_tokens > 0:
                return model.context_window / model.cost_per_1k_tokens
            return model.context_window  # free models score by context
        else:  # balanced
            # Balanced: cost * 0.5 + (1 / context_window) * 0.3 + rpm concerns
            cost_component = model.cost_per_1k_tokens * 0.5
            # Lower RPM limit = potentially more constrained = worse
            rpm_penalty = 0.0
            if model.rpm_limit and model.rpm_limit > 0:
                rpm_penalty = 1.0 / model.rpm_limit
            context_component = model.context_window * 0.000001  # normalize
            return cost_component + rpm_penalty - context_component

        return None


# ──────────────────────────────────────────────────────────────
# Provider-aware capability router
# ──────────────────────────────────────────────────────────────

class MultiProviderRouter:
    """Extends the capability router to support multiple providers.

    Instead of fixed NVIDIA chains, this router can select optimal
    provider/models based on availability, rate limits, cost, and task priority.
    """

    def __init__(self, base_router: CapabilityRouter = None) -> None:
        self.base_router = base_router or CapabilityRouter()
        # Provider state per key (in production would be in Redis/DB)
        self._key_provider_state: Dict[str, Dict[Provider, Tuple[ProviderRateLimit, ProviderBudget]]] = {}

    def get_key_provider_state(self, key_alias: str) -> Dict[Provider, Tuple[ProviderRateLimit, ProviderBudget]]:
        """Get or create rate limit + budget state for a key across all providers."""
        if key_alias not in self._key_provider_state:
            self._key_provider_state[key_alias] = {}
        return self._key_provider_state[key_alias]

    def get_provider_state(
        self, key_alias: str, provider: Provider
    ) -> Tuple[ProviderRateLimit, ProviderBudget]:
        """Get rate limit and budget for a specific key+provider."""
        state = self.get_key_provider_state(key_alias)
        if provider not in state:
            state[provider] = (
                ProviderRateLimit(key_alias=key_alias, provider=provider),
                ProviderBudget(key_alias=key_alias, provider=provider),
            )
        return state[provider]

    def select_model_for_capability(
        self,
        key_alias: str,
        capability: str,
        task_priority: str = "balanced",
        preferred_providers: List[Provider] = None,
    ) -> Optional[dict]:
        """Select the best model for a capability given a key's constraints.

        Returns a dict with model selection info, or None if unavailable.
        """
        # Get this key's provider state
        key_state = self.get_key_provider_state(key_alias)

        rate_limits: Dict[Provider, ProviderRateLimit] = {}
        budgets: Dict[Provider, ProviderBudget] = {}

        for provider in PROVIDER_MODELS.keys():
            rl, bud = key_state.get(provider, (
                ProviderRateLimit(key_alias=key_alias, provider=provider),
                ProviderBudget(key_alias=key_alias, provider=provider),
            ))
            rate_limits[provider] = rl
            budgets[provider] = bud

        # Use smart selector
        result = SmartSelector.select_model(
            capability=capability,
            preferred_providers=preferred_providers,
            key_rate_limits=rate_limits,
            key_budgets=budgets,
            task_priority=task_priority,
        )

        if result is None:
            return None

        provider, model = result

        # Record the selection (consuming 1 RPM for the selected provider)
        rl, bud = key_state[provider]
        rl.record_request(rpm_increment=1)  # 1 RPM consumed
        # Estimate and record cost
        estimated_tokens = 756  # typical: ~500 input + 256 output
        estimated_cost = (estimated_tokens / 1000) * model.cost_per_1k_tokens
        if estimated_cost > 0:  # only track cost for paid models
            bud.record_spend(model.model_name, estimated_cost)

        return {
            "provider": provider,
            "model": model,
            "provider_model_name": model.model_name,
            "capability": capability,
            "task_priority": task_priority,
            "rpm_consumed": 1,
            "estimated_cost_usd": estimated_cost,
            "selection_reason": self._selection_reason(model, task_priority),
        }

    def _selection_reason(self, model: ProviderModelInfo, task_priority: str) -> str:
        """Human-readable reason for model selection."""
        if task_priority == "cost":
            return f"Cost-optimal: ${model.cost_per_1k_tokens}/1k tokens"
        elif task_priority == "speed":
            return f"Speed: {model.rpm_limit} RPM limit, {model.context_window} context"
        elif task_priority == "quality":
            return f"Quality: {model.context_window} context window, {model.display_name}"
        else:
            return f"Balanced: {model.display_name} ({model.provider.name})"

    def list_available_providers(self, capability: str) -> List[str]:
        """List which providers support a given capability."""
        providers = CAPABILITY_PROVIDER_MAP.get(capability, set())
        return [p.name for p in sorted(providers, key=lambda p: p.name)]

    def list_all_models_for_capability(self, capability: str) -> List[dict]:
        """List all models across providers that support a capability."""
        results = []
        for provider, models in PROVIDER_MODELS.items():
            if capability in [c for m in models for c in m.capabilities]:
                for m in models:
                    if capability in m.capabilities:
                        results.append({
                            "provider": provider.name,
                            "model_name": m.model_name,
                            "display_name": m.display_name,
                            "cost_per_1k": m.cost_per_1k_tokens,
                            "context_window": m.context_window,
                            "rpm_limit": m.rpm_limit,
                        })
        return results