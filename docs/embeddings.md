# Embedding Batch Support — llm-gateway

## Overview

The `embed` capability routes to NVIDIA's asymmetric embedding models. These models require
`input_type` to be set per deployment (configured in `config/litellm.yaml`). This document
covers batch embedding, caching, and best practices.

## Configured Embedding Models

| Model | Family | RPM | Input Type | Dimensions |
|-------|--------|-----|------------|------------|
| nemotron-3-embed-1b | nemotron-embed | 2/min | query | 2048 |
| llama-nemotron-embed-vl-1b-v2 | llama-nemotron-embed | 1/min | query | 768 |

Both are asymmetric: `input_type=query` is set per deployment. The fallback chain is
`embed` → `embed.2`.

## Batch Embedding

LiteLLM's `/v1/embeddings` endpoint accepts a list of inputs in a single request.
Batch multiple texts together to amortize the per-request overhead:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://<node>:30400/v1",
    api_key="<project-key>",
)

# Single request with multiple inputs — more efficient than one call per text
texts = [
    "AAPL closed at $150.25, up 2.3%",
    "TSLA down 1.5% on delivery concerns",
    "NVDA earnings beat estimates by 8%",
]

response = client.embeddings.create(
    model="embed",           # capability name, routes through the embed chain
    input=texts,             # list of strings — batched
    encoding_format="float",
)

for i, item in enumerate(response.data):
    vector = item.embedding
    print(f"Text {i}: {len(vector)}-dim vector")
```

**Rate limit:** The `embed` chain allows 2 + 1 = 3 requests/minute total. For large batch jobs,
split across multiple minutes or request a higher `rpm_limit` for your project key.

## Caching Embeddings

Embedding vectors are deterministic for the same model + input. Cache them client-side to
avoid redundant API calls:

```python
import hashlib
import json
from pathlib import Path

CACHE_DIR = Path("./embed_cache")
CACHE_DIR.mkdir(exist_ok=True)

def get_embedding(client, text, model="embed"):
    key = hashlib.sha256(f"{model}:{text}".encode()).hexdigest()[:16]
    cache_file = CACHE_DIR / f"{key}.json"
    
    if cache_file.exists():
        return json.loads(cache_file.read_text())["embedding"]
    
    response = client.embeddings.create(model=model, input=[text])
    embedding = response.data[0].embedding
    
    cache_file.write_text(json.dumps({"embedding": embedding}))
    return embedding
```

## Best Practices

- **Use capability names, not model IDs:** Clients ask for `embed`, never
  `nemotron-3-embed-1b`. This lets you swap models without client changes.
- **Batch inputs:** One request with 10 texts is faster than 10 requests with 1 text each.
- **Cache aggressively:** Embeddings don't change; cache by model + input hash.
- **Watch RPM:** The embed chain is limited to 3 req/min. Large jobs need planning.
- **Handle fallbacks:** If the primary embedder fails, the fallback may return different
  dimensions. Check the `model` field in the response if dimension matters.

## Errors

| Error | Meaning | Action |
|-------|---------|--------|
| 429 | Embed RPM limit exceeded | Wait, retry with backoff |
| 404 | Model not found for account | The model may have been retired — check `ops/smoke.sh --live` |
| 400 | Invalid input format | Ensure `input` is a string or list of strings |
