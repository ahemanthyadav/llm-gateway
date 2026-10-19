#!/bin/bash
# smoke.sh — end-to-end proof inside the running gateway, with NO provider key needed:
#   1. health endpoints answer
#   2. failover: `selftest` (down) must fall back to `selftest.2` and answer SELFTEST-FALLBACK-OK
#   3. project keys: a throw-away key limited to [selftest] at 2 req/min
#        - is refused for a capability it was not granted
#        - gets 429 once it exceeds its request limit
#   4. the throw-away key is deleted again
# With a provider key set, also run:  ops/smoke.sh --live   (one real call per capability)
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
LIVE=${1:-}
kubectl -n llm exec -i deploy/llm-gateway -- python - "$LIVE" <<'EOF'
import json, os, sys, time, urllib.error, urllib.request
BASE, MASTER, live = "http://127.0.0.1:4000", os.environ["LITELLM_MASTER_KEY"], sys.argv[1] == "--live"

def call(path, key, body=None, method=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                                 method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"{}").decode()[:300], {}

def chat(key, model, text="ping"):
    return call("/v1/chat/completions", key, {"model": model, "messages": [{"role": "user", "content": text}], "max_tokens": 64})

ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))

s, _, _ = call("/health/liveliness", MASTER); check("liveliness", s == 200, s)
s, _, _ = call("/health/readiness", MASTER); check("readiness", s == 200, s)
s, body, hdr = chat(MASTER, "selftest")
txt = body["choices"][0]["message"]["content"] if s == 200 else body
check("failover selftest -> selftest.2", s == 200 and txt == "SELFTEST-FALLBACK-OK", txt)

s, k, _ = call("/key/generate", MASTER, {"key_alias": "smoke-temp", "models": ["selftest", "selftest.2"], "rpm_limit": 2})
key = k["key"] if s == 200 else None
check("project key created", key is not None, s)
if key:
    s, body, _ = chat(key, "fast-json")
    check("refused for a capability not granted", s in (400, 401, 403), s)
    codes = [chat(key, "selftest")[0] for _ in range(4)]
    check("request limit enforced (429)", 429 in codes and codes[0] == 200, codes)
    s, _, _ = call("/key/delete", MASTER, {"keys": [key]})
    check("temp key deleted", s == 200, s)

if live:
    for cap in ("fast-json", "general", "reasoning", "long-context"):
        t = time.time()
        s, body, _ = chat(MASTER, cap, "Reply with exactly: OK")
        model = body.get("model") if isinstance(body, dict) else "-"
        check(f"live {cap}", s == 200, f"{s} model={model} {time.time() - t:.1f}s")
        time.sleep(3)
    s, body, _ = call("/v1/embeddings", MASTER, {"model": "embed", "input": ["hello"]})
    check("live embed", s == 200, s)

print("SMOKE-OK" if ok else "SMOKE-FAIL")
sys.exit(0 if ok else 1)
EOF
