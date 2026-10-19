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

## Consequences
- Until then failover works but the order is a guess. `ops/smoke.sh --live` proves reachability, not quality.
- Re-run the bake-off when a provider retires a model or a new provider is added.
