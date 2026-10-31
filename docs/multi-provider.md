# Multi-Provider Setup Guide — llm-gateway

## Overview

The llm-gateway supports 6 providers: NVIDIA, Google Gemini, Groq, Cloudflare Workers AI,
GitHub Models, and Cerebras. The provider model catalog (`arch/provider_model.py`) defines
18+ models with capabilities, costs, and rate limits. `config/litellm.yaml` is currently
NVIDIA-only; this guide shows how to add non-NVIDIA providers.

## Prerequisites

1. Provider API keys stored as secrets in Kubernetes (`Secret llm/llm-gateway`)
2. Provider env vars wired into `manifests/gateway.yaml` (already done in this commit)
3. Model entries in `config/litellm.yaml` (already added for Groq and Google Gemini)
4. Fallback chain references uncommented in `config/litellm.yaml`

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
```

Each command reads the key from a local env file (never printed), base64-encodes it,
patches the Kubernetes secret, and restarts the gateway.

## Step 2: Enable Models in config/litellm.yaml

Non-NVIDIA models are already defined in `config/litellm.yaml` under the
"non-NVIDIA providers" section. To activate them, uncomment their fallback references
in `litellm_settings.fallbacks`:

```yaml
fallbacks:
  - fast-json: [fast-json.2, fast-json.3, groq-mixtral]     # uncomment groq-mixtral
  - general: [general.2, fast-json, gemini-flash]           # uncomment gemini-flash
  - reasoning: [reasoning.2, general, gemini-pro]           # uncomment gemini-pro
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
```

## Provider Capability Matrix

| Capability | NVIDIA | Groq | Google Gemini | Cloudflare | GitHub | Cerebras |
|------------|--------|------|---------------|------------|--------|----------|
| fast-json  | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| general    | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| reasoning  | ✅ | ❌ | ✅ | ❌ | ❌ | ✅ |
| long-context | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| embed      | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

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
