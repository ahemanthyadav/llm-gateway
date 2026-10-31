# Pending Tasks — llm-gateway

All architecture modules are built and verified. These are the remaining improvements, grouped by tier.
Items marked **[no deps]** can be done immediately; items with dependencies must wait.

## Tier 1 — High Value (Safety & Observability)

| # | Task | Status | Deps |
|---|------|--------|------|
| 1 | Budget enforcement at request time (402 over budget, record spend after call) | **implemented** | arch/budget_enforcer.py |
| 2 | Redis-backed rate limiter + budget tracker (multi-replica safe) | **implemented** | arch/redis_state.py |
| 3 | Prometheus metrics endpoint (`/metrics`) | **implemented** | arch/metrics.py |
| 4 | `ops/delete-project.sh` — revoke/delete a project key | ✅ done | none |
| 5 | `ops/probe-models.sh` — probe model availability before adding to config | ✅ done | none |
| 6 | `arch/cost_estimator.py` — CLI cost/RPM feasibility estimator | ✅ done | none |
| 7 | Wire provider env vars into `manifests/gateway.yaml` | ✅ done | none |

## Tier 2 — Medium Value (Resilience & Operations)

| # | Task | Status | Deps |
|---|------|--------|------|
| 8 | Add non-NVIDIA models to `config/litellm.yaml` fallbacks | **implemented** | provider keys set |
| 9 | Canary / blue-green deployments (`ops/deploy.sh --canary`) | **implemented** | deploy.sh updated |
| 10 | `ops/rotate-keys.sh` — automated key rotation | **implemented** | new script |
| 11 | `ops/backup-db.sh` — automated `litellm` DB backups | **implemented** | new script |
| 12 | Client resilience examples (retry/backoff on 429/5xx) | **implemented** | examples/ |

## Tier 3 — Documentation & Polish

| # | Task | Status | Deps |
|---|------|--------|------|
| 13 | Embedding batch support documentation | **implemented** | docs/embeddings.md |
| 14 | Secret rotation procedures | **implemented** | docs/operations.md |
| 15 | Multi-provider setup guide | **implemented** | docs/multi-provider.md |

---

**Complete:** All 6 arch modules, test_config.py (8/8), ops/deploy.sh, ops/smoke.sh, AGENTS.md, gateway deployed SMOKE-OK on TX2.

**Infrastructure items still needing manual k8s changes:**
- Redis deployment (for Tier 1 #2 to be active at runtime)
- Prometheus server + service (for Tier 1 #3 to be scraped)
- TimescaleDB backup schedule (cronjob for Tier 2 #11)
