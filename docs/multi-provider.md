# Multi-Provider Setup Guide — llm-gateway

## Overview

The llm-gateway supports 10 providers: NVIDIA, Google Gemini, Groq, Cloudflare Workers AI,
GitHub Models, Cerebras, OpenAI, Anthropic, OpenRouter, and Ollama. The provider model
catalog (`arch/provider_model.py`) defines 26+ models with capabilities, costs, and rate
limits. `config/litellm.yaml` currently has NVIDIA models in active chains; non-NVIDIA
models are defined but not in active fallback chains until you set keys and enable them.

## Prerequisites

1. Provider API keys stored as secrets in Kubernetes (`Secret llm/llm-gateway`)
2. Provider env vars wired into `manifests/gateway.yaml` (already done — includes NVIDIA,
   Google AI, Groq, Cloudflare, GitHub, Cerebras, OpenRouter, Ollama)
3. Model entries in `config/litellm.yaml` (already added for Groq, Google Gemini,
   OpenRouter, and Ollama)
4. Fallback chain references added in `config/litellm.yaml` (see Step 2)

## Step 1: Add Provider Keys

```bash
# Google AI
ops/set-provider-key.sh google-ai-key ../marketdata/.secrets.env GOOGLE_AI_API_KEY

# Groq
ops/set-provider-key.sh groq-api-key ../marketdata/.secrets.env GROQ_API_KEY

# Cloudflare Workers AI
ops/set-provider-key.sh cloudflare-api-key ../marketdata/.secrets.env CLOUDFLARE_API_KEY

# GitHub Models
ops/set-provider-key.sh github-api-key ../marketdata/.secrets.env GITHUB_API_KEY

# Cerebras
ops/set-provider-key.sh cerebras-api-key ../marketdata/.secrets.env CEREBRAS_API_KEY
# OpenRouter
ops/set-provider-key.sh openrouter-api-key ../marketdata/.secrets.env OPENROUTER_API_KEY
# Ollama (base URL, not an API key)
ops/set-provider-key.sh ollama-base-url ../marketdata/.secrets.env OLLAMA_BASE_URL
```

Each command reads the key from a local env file (never printed), base64-encodes it,
patches the Kubernetes secret, and restarts the gateway.

## Step 2: Enable Models in config/litellm.yaml

Non-NVIDIA models are already defined in `config/litellm.yaml` under the
"non-NVIDIA providers" section. To activate them, uncomment their fallback references
in `litellm_settings.fallbacks`:

```yaml
fallbacks:
  - fast-json: [fast-json.2, fast-json.3, groq-mixtral, openrouter-llama-8b]
  - general: [general.2, fast-json, gemini-flash, ollama-llama3.2]
  - reasoning: [reasoning.2, general, gemini-pro, ollama-llama3.1]
  - long-context: [long-context.2, gemini-pro]
```

Then deploy:
```bash
python3 tests/test_config.py && ops/deploy.sh && ops/smoke.sh --live
```

## Step 3: Verify Provider Reachability

Before adding a model to active fallbacks, probe it:

```bash
ops/probe-models.sh --provider groq --models mixtral-8x7b-32768,llama3-8b-8192
ops/probe-models.sh --provider google --models gemini-1.5-flash,gemini-1.5-pro \
  --key-field google-ai-key
ops/probe-models.sh --provider openrouter --models meta-llama/llama-3.1-8b-instruct \
  --key-field openrouter-api-key
ops/probe-models.sh --provider ollama --models llama3.2,llama3.1 \
  --key-field ollama-base-url
```

## Provider Capability Matrix

| Capability | NVIDIA | Groq | Google Gemini | Cloudflare | GitHub | Cerebras | OpenAI | Anthropic | OpenRouter | Ollama |
|------------|--------|------|---------------|------------|--------|----------|--------|-----------|------------|--------|
| fast-json  | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ |
| general    | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| reasoning  | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| long-context | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ |
| embed      | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

## Cost-Aware Selection

Use `arch/cost_estimator.py` to estimate costs before sending traffic:

```bash
# Estimate cost for 1000 fast-json requests at lowest cost
python3 arch/cost_estimator.py --capability fast-json --requests 1000 --priority cost

# Check if a project with $5 budget can afford 500 reasoning requests
python3 arch/cost_estimator.py --capability reasoning --requests 500 --priority balanced --max-budget-usd 5.0
```

## Notes

- **NVIDIA free tier:** 30 RPM total across all NVIDIA deployments. Non-NVIDIA models
  do not count toward this limit.
- **Paid models:** Only add paid models to chains used by projects with a budget
  (AGENTS.md rule #5). Budget enforcement is implemented in `arch/budget_enforcer.py`.
- **Fallback diversification:** Cross-family diversification (ADR 0001) still applies —
  don't put two models from the same family in one chain unless necessary.
- **OpenRouter:** One API key gives access to hundreds of models. Set
  `openrouter-api-key` in the secret. Models are prefixed with `openrouter/` in the
  `model` field. Pricing varies by model — check OpenRouter's pricing page before adding
  to paid chains.
- **Ollama:** Self-hosted, zero API cost. Set `ollama-base-url` (e.g.,
  `http://ollama-service.ollama.svc.cluster.local:11434`) in the secret. Ollama models
  don't need an API key — set `api_key: unused` in config. RPM limit is effectively
  limited by your local hardware, not the provider.
- **OpenAI / Anthropic:** Models are defined in the catalog but not yet added to
  `config/litellm.yaml`. Add them following the same pattern as Groq/Gemini, then set
  `openai-api-key` or `anthropic-api-key` via `ops/set-provider-key.sh`.
