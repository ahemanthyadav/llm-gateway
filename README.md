# llm-gateway

One shared, OpenAI-compatible LLM endpoint for every project on the home lab — many AI providers
behind stable **capability names**, automatic failover, per-project keys/limits/budgets, usage
logging. Runs on the k3s cluster (TX2), built on [LiteLLM](https://docs.litellm.ai) 1.106.0.

```
projects (any language / OS) ──OpenAI API + project key──▶ llm-gateway ──▶ NVIDIA (now) · any provider (later)
```

## Use it from a project

| Where the client runs | Base URL |
|---|---|
| inside the cluster | `http://llm-gateway.llm.svc.cluster.local:4000/v1` |
| LAN / tailnet machine | `http://<any-cluster-node>:30400/v1` |

Ask for a **capability**, never a vendor model:

| Capability | For | Failover chain (see `config/litellm.yaml`) |
|---|---|---|
| `fast-json` | short structured output: summaries, extraction | 3 models, 3 families |
| `general` | everyday chat / writing | 2 models → `fast-json` |
| `reasoning` | harder multi-step questions | 2 models → `general` |
| `long-context` | big inputs | 2 models |
| `embed` | embeddings (`/v1/embeddings`) | 2 models |

The response's `model` field says which model actually answered. Examples: `examples/` (curl, Python,
Node, OpenCode). Any OpenAI-compatible SDK or tool works — that is the whole client contract.

**Your project is responsible for:** what data it sends (no personal data to free providers), validating
answers, and behaving well when the gateway or every provider is down (degrade, never block).

## Add a project
```bash
ops/new-project.sh <project> <k8s-namespace> fast-json,general 10 0     # capabilities, req/min, $ budget (0 = free only)
```
Stores the key (never printed) as Secret `<namespace>/llm-gateway-key` (`api-key`, `base-url`). For a client
outside the cluster, read it from that Secret into the client's own secret store.

## Add a provider or change models
1. Key: `ops/set-provider-key.sh <field> <env-file> <VAR>` (+ an `env` entry in `manifests/gateway.yaml`).
2. Models: edit `config/litellm.yaml` — new deployments, fallback chains. Free tiers first; paid models only in
   chains used by projects with a budget.
3. `python3 tests/test_config.py && ops/deploy.sh && ops/smoke.sh` (`--live` once a key exists).

Clients change nothing.

## Operate
| Task | Command |
|---|---|
| first install | `ops/bootstrap.sh` (DB + Secret) → `ops/deploy.sh` → `ops/smoke.sh` |
| deploy config/manifest change | `ops/deploy.sh` |
| prove it works (no key needed) | `ops/smoke.sh` — failover, key scoping, rate limit |
| real calls | `ops/smoke.sh --live` |
| admin UI (keys, usage) | `http://<node>:30400/ui` — log in with the master key (Secret `llm/llm-gateway`, field `master-key`) |

Details, gotchas and recovery: `docs/operations.md`. Decisions: `docs/adr/`.
