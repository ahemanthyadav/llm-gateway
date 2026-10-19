# 0001. One shared LLM gateway (LiteLLM) with capability names

- Date: 2026-10-18
- Status: accepted (owner: own repo, TX2 host, many providers, any client platform, several projects;
  OpenCode joins later as its own project)

## Context
Several projects will use LLMs (marketdata first). Without a shared layer each project re-implements provider keys,
failover, rate limiting and usage tracking, is locked to one vendor's model names, and shares the NVIDIA free tier's
~40 requests/min account limit with no coordination. Options: a client library per language (no shared limits, keys
everywhere), a self-written proxy (re-implements failover/limits/keys), or an existing gateway. Among gateways LiteLLM
was verified for every requirement: NVIDIA provider, ordered fallbacks across groups, retries + cooldowns, per-deployment
rpm, per-key model access/rpm/budget, OpenAI-compatible API, official arm64 image.

## Decision
We run one LiteLLM proxy (namespace `llm`, TX2) behind an OpenAI-compatible API. Clients ask for **capabilities**
(`fast-json`, `general`, `reasoning`, `long-context`, `embed`) that map in one git-tracked file to ordered chains of
models from different families/providers; provider keys live only in the gateway; every project has its own key with
allowed capabilities, request limit and budget. Routing is never edited in the UI (`store_model_in_db: false`).

## Consequences
- Adding a provider or swapping a model is a config change; no client changes. Capability names are a public contract.
- The gateway is a shared dependency: every client must degrade gracefully when it is down.
- Single worker (no Redis): limits and cooldowns are per process — fine for one replica; revisit with a second replica.
- OpenCode is not routed through it initially (shared free quota, weaker models for coding agents, the repair tool must
  not depend on the thing it repairs); it may join later as its own project with its own capability and limit.
