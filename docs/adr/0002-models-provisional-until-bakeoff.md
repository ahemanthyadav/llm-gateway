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
`enable_thinking: false` on the `fast-json` primary (see operations.md). `ops/smoke.sh --live` → SMOKE-OK.

## Bake-off result (2026-10-19, fast-json quality)
10 trading days of marketdata facts × 5 candidate groups, scored by the client's full number+direction check:

| group (model) | first-try pass | final pass | median latency |
|---|---|---|---|
| fast-json.2 (gemma-4-31b-it) | 100 % | 100 % | 11.7 s |
| general.2 (gemma-4-31b-it) | 100 % | 100 % | 11.7 s |
| general (gpt-oss-20b) | 100 % | 90 % | 9.9 s |
| fast-json (nemotron-3.5-lightning, thinking off) | 90 % | 100 % | 1.8 s |
| fast-json.3 (gpt-oss-20b) | 90 % | 90 % | 15.0 s |

**Order kept as-is.** After the built-in retry the top four all reach 100 % final quality, and the current primary is
~6× faster with no JSON-fence quirk; 10 runs is too small a sample to pay that latency for one first-try difference.
Revisit only if narrative quality regresses; re-run the bake-off when a model is retired or added.

## Consequences
- Until then failover works but the order is a guess. `ops/smoke.sh --live` proves reachability, not quality.
- Re-run the bake-off when a provider retires a model or a new provider is added.
