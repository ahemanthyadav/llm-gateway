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
   - 6 providers: `NVIDIA`, `GOOGLE_GEMINI`, `GROQ`, `CLOUDFLARE_WORKERS_AI`, `GITHUB_MODELS`, `CEREBRAS`.
   - 18+ models with `cost_per_1k_tokens`, `rpm_limit`, `context_window`, `capabilities`.
   - `CAPABILITY_PROVIDER_MAP`: which providers support `fast-json`, `general`, `reasoning`, `long-context`, `embed`.
   - `SmartSelector.select_model(capability, key_rate_limits, key_budgets, task_priority)` → `(Provider, ProviderModelInfo)`.
   - `MultiProviderRouter`: manages per-key provider state, `select_model_for_capability(key_alias, capability)`.

10. **`arch/litellm_config.py`** — Generates valid `config/litellm.yaml` from architectural data model. Use `generate_reference_config(path)` to produce the reference config.

11. **`ops/new-project.sh`** — Enhanced: uses Python inside the gateway to generate keys, validate scoping via `KeyScoper`, and deploy the key as a namespace Secret.

12. **`ops/set-provider-key.sh`** — Enhanced: validates field name format, checks env file exists, supports known provider fields
    (`nvidia-nim-api-key`, `google-ai-key`, `groq-api-key`, `cloudflare-api-key`, `github-api-key`, `cerebras-api-key`), restarts gateway.

13. **`ops/bootstrap.sh`** — Updated: documents next steps after boot (add provider keys, create project, deploy, smoke test, admin UI).

13. **`ops/deploy.sh`** — Enhanced: runs `test_config.py` + diversification validation before deploying ConfigMap + rolling pod. Outputs deployment SHA.

## 📁 Key Repository Structure

| Directory | Purpose |
|-----------|---------|
| `arch/` | Architecture modules (capability routing, fallback diversification, RPM/budget, project keys, provider model, litellm config gen) |
| `config/` | `litellm.yaml` — single source of truth for model routing (git-tracked, never edit in UI) |
| `ops/` | Deployment/ops bootstrap scripts |
| `docs/operations.md` | Detailed operational guidance |
| `docs/adr/` | Architecture decision records |
| `tests/` | Validation: `test_config.py` (8 tests, must pass before deploy) |

## 📋 Verification Commands

| Action | Command |
|--------|---------|
| Validate config + diversification | `python3 tests/test_config.py` |
| Quick RPM/budget test | `python3 -c "from arch.rpm_budget import RpmBudgetTracker, PerKeyRateLimiter, PerKeyBudget; ..."` |
| Test key scoping | `python3 -c "from arch.project_key import ProjectKeyConfig, KeyScoper; ..."` |
| Multi-provider selection | `python3 -c "from arch.provider_model import SmartSelector, Provider; ..."` |
| Full smoke test | `ops/smoke.sh` (or `ops/smoke.sh --live` for real provider calls) |
| Deploy after changes | `ops/deploy.sh` |
| Admin UI | `http://<node>:30400/ui` — login with master key from `Secret llm/llm-gateway` |

## 📦 What Was Just Deployed

The latest commit (`e9fd631`) adds 6 new architecture modules, enhances 4 ops scripts, and updates the deployment flow. The gateway pod rolled out successfully with `SMOKE-OK`. All existing rules (secrets, routing in git, capability contracts, `gw_` prefix, NVIDIA RPM budget, cluster rules) remain in effect.