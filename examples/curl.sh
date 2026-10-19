#!/bin/bash
# Any shell, any OS with curl. LLM_KEY = your project key; LLM_URL = base URL (README).
curl -s "${LLM_URL:-http://llm-gateway.llm.svc.cluster.local:4000/v1}/chat/completions" \
  -H "Authorization: Bearer $LLM_KEY" -H "Content-Type: application/json" \
  -d '{"model": "fast-json", "messages": [{"role": "user", "content": "Reply with JSON {\"ok\": true}"}],
       "response_format": {"type": "json_object"}, "max_tokens": 50}'
