# Operations — llm-gateway

> Verified 2026-10-18 on the cluster: pod on ahytx2-desktop, 642 MiB at idle, `ops/smoke.sh` → SMOKE-OK
> (failover, key scoping 403, per-key rate limit 429), OpenAI Python SDK from the workstation via NodePort OK.

## Layout
| Thing | Where |
|---|---|
| Deployment / Services | namespace `llm`: `llm-gateway` (ClusterIP :4000), `llm-gateway-nodeport` (:30400 on every node) |
| Node | TX2 (`nodeSelector`, gpu toleration) — 7.7 GB RAM; Pis (1 GB) are too small |
| Image | `local/litellm-database:1.106.0` = `ghcr.io/berriai/litellm-database@sha256:80a12a210e6626e39daaa31fb6ce70f4c4d97ee10e21d4584a9e87f45bf3a2f1` (official arm64), imported into TX2 containerd; tarball `/mnt/tx2-ssd/image-tarballs/litellm-database-1.106.0.tar.gz` (sha256 in `SHA256SUMS.all`) |
| Config | ConfigMap `llm-gateway-config` built from `config/litellm.yaml` by `ops/deploy.sh` (pod rolls on change) |
| Secrets | `llm/llm-gateway`: `master-key`, `salt-key`, `database-url`, provider keys (`nvidia-nim-api-key`, …) |
| Database | `litellm` DB (owner role `litellm`) on the marketdata TimescaleDB server; keys, budgets, spend logs |

## Gotchas (found while building)
- **`model_info.tier` is reserved by LiteLLM** (free/paid key routing): a custom `tier` value made every deployment
  "unhealthy" ("There are no healthy deployments"). Our own metadata uses the `gw_` prefix (`gw_family`, `gw_provider`,
  `gw_cost`). Never add un-prefixed custom keys to `model_info`.
- Fallbacks are between **model groups**; deployments sharing one `model_name` are load-balanced, not ordered. That is
  why chains are `<cap>` → `<cap>.2` → `<cap>.3`.
- NVIDIA's free-tier limit is per account; per-deployment `rpm` values must sum to ≤ 30 (tested).
- `--num_workers 1`: rate limits and cooldowns are in-process; more workers would need Redis to share them.
- **"Function '…': Not found for account"** (404) — many models in NVIDIA's public catalogue are not enabled for a
  given free account (2026-10-19: kimi-k2.6, mistral-*, gemma-3, several embedders). Probe with the real key before
  adding a model; `ops/smoke.sh --live` catches a dead primary.
- **Reasoning models eat `max_tokens`.** nemotron-3.5-lightning with 400 tokens returned `finish_reason=length` and
  empty content (all spent on reasoning). `fast-json`'s primary therefore runs with
  `extra_body: {chat_template_kwargs: {enable_thinking: false}}` (0.7 s, same answers); `/no_think` in the prompt and
  `reasoning_effort: none` did NOT work. Clients still leave headroom for reasoning fallbacks.
- Some models wrap JSON in a ```` ```json ```` block even with `response_format: json_object` (gemma-4) — clients strip fences.
- Embeddings: NVIDIA's asymmetric embedders need `input_type` (set per deployment: `query`).
- The salt key encrypts credentials stored in the DB — never rotate it casually (bootstrap keeps it).

## Recovery
- Pod crash-loops after a config change → `kubectl -n llm logs deploy/llm-gateway`; revert the config commit, `ops/deploy.sh`.
- DB lost → keys/usage are gone; routing is unaffected (it lives in git). `ops/bootstrap.sh`, redeploy, re-run
  `ops/new-project.sh … --rotate` per project.
- Image lost on the TX2 → `k3s ctr -n k8s.io images import <tarball above>`.
- Backups: the `litellm` DB is **not** in marketdata's daily `pg-backup` (that dumps the `postgres` DB) — acceptable
  (keys are re-creatable); add it if usage history starts to matter.
