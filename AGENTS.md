# llm-gateway — agent guide

Shared LLM gateway (LiteLLM 1.106.0) for all home-lab projects. Read `README.md`, `docs/operations.md`, `docs/adr/`.

Rules:
1. **Never print or commit a secret.** Provider keys, the master key, salt key and project keys live only in k8s
   Secrets (`llm/llm-gateway`, `<ns>/llm-gateway-key`). Scripts read/move them without echoing. No IPs in tracked files.
2. **Routing lives in `config/litellm.yaml`** (git) — never in the admin UI. Run `python3 tests/test_config.py`
   before `ops/deploy.sh`; then `ops/smoke.sh`.
3. **Capability names are a public contract** (`fast-json`, `general`, `reasoning`, `long-context`, `embed`).
   Add new ones; never rename or remove one without migrating every project.
4. **`model_info` custom keys use the `gw_` prefix** — `tier` and other bare names are reserved by LiteLLM.
5. NVIDIA free tier: per-deployment `rpm` sum ≤ 30 (tested). Paid models only in chains of projects with a budget.
6. Cluster rules from the marketdata repo apply (pi2 fragile, no registry, never `crictl rmi --prune`, TX2 config
   load-bearing): `../marketdata/AGENTS.md`.
