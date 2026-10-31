# llm-gateway — agent guide

Shared LLM gateway (LiteLLM 1.106.0) for all home-lab projects. Read `README.md`, `docs/operations.md`, `docs/adr/`.

## ⚠️ Critical Rules (never break these)

1. **Never print or commit a secret.** Provider keys, the master key, salt key and project keys live only in k8s
   Secrets (`llm/llm-gateway`, `<ns>/llm-gateway-key`). Scripts read/move them without echoing. No IPs in tracked files.

2. **Routing lives in `config/litellm.yaml`** (git) — never in the admin UI. Run `python3 tests/test_config.py`
   before `ops/deploy.sh`; then `ops/smoke.sh`.

3. **Capability names are a public contract** (`fast-json`, `general`, `reasoning`, `long-context`, `embed`).
   Add new ones; never rename or remove one without migrating every project.

4. **`model_info` custom keys use the `gw_` prefix** — `tier` and other bare names are reserved by LiteLLM.

5. **NVIDIA free tier: per-deployment `rpm` sum ≤ 30** (tested). Paid models only in chains of projects with a budget.

6. **Cluster rules from the marketdata repo apply** (pi2 fragile, no registry, never `crictl rmi --prune`, TX2 config
   load-bearing): `../marketdata/AGENTS.md`.

## 🆕 Architecture Enhancements (new in this session)

5. **`arch/capability_router.py`** — Core routing: maps capability names to fallback chains read from `config/litellm.yaml`. Validates cross-family diversification (ADR 0001). Entry point: `CapabilityRouter()`.

6. **`arch/fallback_diversification.py`** — Enforces that each capability's fallback chain contains models from different `gw_family` values. Raises violation if a chain has only one family.

7. **`arch/rpm_budget.py`** — Three enforcement layers:
   - `RpmBudgetTracker`: total NVIDIA RPM ≤ 30 (free-tier headroom). Validate with `check_budget()`.
   - `PerKeyRateLimiter(rpm_limit)`: sliding-window per-key rate limit. `try_consume(key)` → `(allowed, wait_seconds)`.
   - `PerKeyBudget(key_alias, max_budget_usd)`: cumulative USD spend. `record_spend(amount)` + `budget_exceeded()`.

8. **`arch/project_key.py`** — Key lifecycle:
   - `generate_project_key()` → `sk-` + 48 random chars.
   - `ProjectKeyConfig` dataclass: `key_alias`, `api_key`, `base_url`, `capabilities`, `rpm_limit`, `max_budget_usd`, `budget_duration`, `metadata`.
   - `KeyScoper(router, key_config)`: validates capabilities are known, RPM > 0, budget duration valid.
   - `deploy_project_key(key_config)`: simulates `/key/generate` API response.

9. **`arch/provider_model.py`** — Multi-provider support structure:
   - 10 providers: `NVIDIA`, `GOOGLE_GEMINI`, `GROQ`, `CLOUDFLARE_WORKERS_AI`, `GITHUB_MODELS`, `CEREBRAS`, `OPENAI`, `ANTHROPIC`, `OPENROUTER`, `OLLAMA`.
   - 26+ models with `cost_per_1k_tokens`, `rpm_limit`, `context_window`, `capabilities`.
   - `CAPABILITY_PROVIDER_MAP`: which providers support `fast-json`, `general`, `reasoning`, `long-context`, `embed`.
   - `SmartSelector.select_model(capability, key_rate_limits, key_budgets, task_priority)` → `(Provider, ProviderModelInfo)`.
   - `MultiProviderRouter`: manages per-key provider state, `select_model_for_capability(key_alias, capability)`.

10. **`arch/litellm_config.py`** — Generates valid `config/litellm.yaml` from architectural data model. Use `generate_reference_config(path)` to produce the reference config.

11. **`arch/budget_enforcer.py`** — Budget enforcement middleware: checks `can_proceed(estimated_cost)` before calls, `record_actual_spend()` after. Raises `BudgetExceededError` when over budget.

12. **`arch/redis_state.py`** — Redis-backed `RedisRateLimiter` and `RedisBudgetTracker` for multi-replica deployments. Survives pod restarts, shared across replicas. `RedisStateManager` convenience wrapper.

13. **`arch/metrics.py`** — Prometheus metrics definitions: request count, duration, rate-limited, budget-blocked, budget spent/remaining, failover, uptime. `start_metrics_server(port)` exposes `/metrics`.

14. **`ops/new-project.sh`** — Enhanced: uses Python inside the gateway to generate keys, validate scoping via `KeyScoper`, and deploy the key as a namespace Secret.

15. **`ops/delete-project.sh`** — Revoke/delete a project key (symmetry with `new-project.sh`). Removes Secret `<namespace>/llm-gateway-key`.

16. **`ops/rotate-keys.sh`** — Rotate a project key: revoke old key, project must re-run `new-project.sh`. Supports `--all` and `--dry-run`.

17. **`ops/set-provider-key.sh`** — Enhanced: validates field name format, checks env file exists, supports known provider fields
    (`nvidia-nim-api-key`, `google-ai-key`, `groq-api-key`, `cloudflare-api-key`, `github-api-key`, `cerebras-api-key`, `openrouter-api-key`, `ollama-base-url`), restarts gateway.

18. **`ops/probe-models.sh`** — Probe provider models for 404 "not found for account" before adding to `config/litellm.yaml`.

19. **`ops/bootstrap.sh`** — Updated: documents next steps after boot (add provider keys, create project, deploy, smoke test, admin UI).

20. **`ops/deploy.sh`** — Enhanced: runs `test_config.py` + diversification validation before deploying ConfigMap + rolling pod. Supports `--canary` (deploy without rolling) and `--promote <sha>` (promote canary to full rollout). Outputs deployment SHA.

21. **`ops/backup-db.sh`** — Backs up the `litellm` TimescaleDB database to gzipped SQL with retention policy. Not part of marketdata's daily pg-backup.

22. **`ops/smoke.sh`** — End-to-end smoke test with optional `--live` for real provider calls.

## 📁 Key Repository Structure

| Directory | Purpose |
|-----------|---------|
| `arch/` | Architecture modules (routing, diversification, RPM/budget, budget enforcement, Redis state, Prometheus metrics, project keys, provider model, config gen) |
| `config/` | `litellm.yaml` — single source of truth for model routing (git-tracked, never edit in UI) |
| `ops/` | Deployment/ops bootstrap scripts |
| `docs/` | operations.md, ADRs, embeddings.md, multi-provider.md |
| `examples/` | curl.sh, python_client.py, node_client.mjs, opencode-provider.jsonc, client_resilience.py |
| `tests/` | Validation: `test_config.py` (8 tests, must pass before deploy) |

## 📋 Verification Commands

| Action | Command |
|--------|---------|
| Validate config + diversification | `python3 tests/test_config.py` |
| Quick RPM/budget test | `python3 -c "from arch.rpm_budget import RpmBudgetTracker, PerKeyRateLimiter, PerKeyBudget; ..."` |
| Test key scoping | `python3 -c "from arch.project_key import ProjectKeyConfig, KeyScoper; ..."` |
| Multi-provider selection | `python3 -c "from arch.provider_model import SmartSelector, Provider; ..."` |
| Cost estimation | `python3 arch/cost_estimator.py --capability <cap> --requests <N> --priority <cost|speed|quality|balanced>` |
| Full smoke test | `ops/smoke.sh` (or `ops/smoke.sh --live` for real provider calls) |
| Deploy after changes | `ops/deploy.sh` |
| Admin UI | `http://<node>:30400/ui` — login with master key from `Secret llm/llm-gateway` |

## ⏳ Completed Tasks (all suggestions implemented)

| # | Task | Status |
|---|------|--------|
| 1 | Budget enforcement at request time | ✅ `arch/budget_enforcer.py` |
| 2 | Redis-backed rate limiter + budget tracker | ✅ `arch/redis_state.py` |
| 3 | Prometheus metrics endpoint | ✅ `arch/metrics.py` |
| 4 | `ops/delete-project.sh` — revoke/delete a project key | ✅ done |
| 5 | `ops/probe-models.sh` — probe model availability | ✅ done |
| 6 | `arch/cost_estimator.py` — CLI cost/RPM feasibility estimator | ✅ done |
| 7 | Wire provider env vars into `manifests/gateway.yaml` | ✅ done |
| 8 | Add non-NVIDIA models to `config/litellm.yaml` | ✅ done (Groq, Gemini defined) |
| 9 | Canary / blue-green deployments | ✅ `ops/deploy.sh --canary` / `--promote` |
| 10 | `ops/rotate-keys.sh` — automated key rotation | ✅ done |
| 11 | `ops/backup-db.sh` — automated `litellm` DB backups | ✅ done |
| 12 | Client resilience examples | ✅ `examples/client_resilience.py` |
| 13 | Embedding batch documentation | ✅ `docs/embeddings.md` |
| 14 | Secret rotation procedures | ✅ `docs/operations.md` |
| 15 | Multi-provider setup guide | ✅ `docs/multi-provider.md` |

**Remaining infrastructure (requires k8s changes outside this repo):**
- Redis deployment (for `arch/redis_state.py` to be active at runtime)
- Prometheus server + service (for `arch/metrics.py` to be scraped)
- TimescaleDB backup cronjob (schedule `ops/backup-db.sh`)


## 📦 What Was Just Deployed

The latest commit (`e9fd631`) adds 6 new architecture modules, enhances 4 ops scripts, and updates the deployment flow. The gateway pod rolled out successfully with `SMOKE-OK`. All existing rules (secrets, routing in git, capability contracts, `gw_` prefix, NVIDIA RPM budget, cluster rules) remain in effect.