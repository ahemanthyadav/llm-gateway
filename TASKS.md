# Pending Tasks — llm-gateway

All architecture modules are built and verified. These are the remaining improvements, grouped by tier.
Items marked **[no deps]** can be done immediately; items with dependencies must wait.

## Tier 1 — High Value, Low Effort (start now)

| # | Task | Deps | Status |
|---|------|------|--------|
| 1 | `ops/delete-project.sh` — revoke/delete a project key (symmetry with `new-project.sh`) | [no deps] | pending |
| 2 | `ops/probe-models.sh` — probe a provider's models for 404 "not found for account" before adding to config | [no deps] | pending |
| 3 | `arch/cost_estimator.py` — CLI: estimate cost/RPM feasibility for N requests at a given priority | [no deps] | pending |
| 4 | Wire provider env vars into `manifests/gateway.yaml` (Google AI, Groq, Cloudflare, GitHub, Cerebras) | [no deps] | pending |
| 5 | Document pending tasks in `AGENTS.md` | [no deps] | pending |

## Tier 2 — Medium Value, Medium Effort

| # | Task | Deps | Status |
|---|------|------|--------|
| 6 | Add 1-2 non-NVIDIA models to `config/litellm.yaml` fallbacks | #4, provider keys set | pending |
| 7 | Budget enforcement at request time (402 when over budget, record spend after call) | LiteLLM middleware integration | pending |
| 8 | Prometheus metrics endpoint (`/metrics`) | LiteLLM integration or sidecar | pending |

## Tier 3 — Future / Scaling

| # | Task | Deps | Status |
|---|------|------|--------|
| 9 | Redis-backed rate-limit + budget state | Multi-replica need | pending |
| 10 | Canary / blue-green deployments | Multi-replica + Redis | pending |
| 11 | Usage reports / per-project spend dashboards | Metrics + budget tracking | pending |

## Tier 4 — Polish / Documentation

| # | Task | Deps | Status |
|---|------|------|--------|
| 12 | Client resilience examples (retry/backoff on 429/5xx) | [no deps] | pending |
| 13 | Embedding batch support documentation | [no deps] | pending |

---

**Complete:** All 6 arch modules, test_config.py (8/8), ops/deploy.sh, ops/smoke.sh, AGENTS.md, gateway deployed SMOKE-OK on TX2.
