# 0002. NVIDIA models are provisional until a bake-off with a real key

- Date: 2026-10-18
- Status: accepted

## Context
The capability chains were filled from NVIDIA's public model list (81 models, 2026-10-18) by family diversity and size,
without any real call (no key yet). Model quality for our tasks (short JSON, numbers copied faithfully) is unmeasured.

## Decision
Once the NVIDIA key is set, run a bake-off per capability: each candidate on the same real prompts (for `fast-json`:
10 days of marketdata facts), scored by the client's validator pass rate, latency and refusal rate. The winner becomes
the primary, the next two from other families the fallbacks. Model ids stay pinned (no `latest` aliases — tested).

## Update 2026-10-19
Key placed. A live probe replaced every model the account cannot reach (404 "not found for account") and set
`enable_thinking: false` on the `fast-json` primary (see operations.md). `ops/smoke.sh --live` → SMOKE-OK. Quality order is
still unmeasured: the bake-off (marketdata `manifests/llm/bakeoff.py`) decides it.

## Consequences
- Until then failover works but the order is a guess. `ops/smoke.sh --live` proves reachability, not quality.
- Re-run the bake-off when a provider retires a model or a new provider is added.
