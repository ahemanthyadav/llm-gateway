"""Python — standard OpenAI SDK (pip install openai). No gateway-specific code."""
import os
from openai import OpenAI

client = OpenAI(base_url=os.environ.get("LLM_URL", "http://llm-gateway.llm.svc.cluster.local:4000/v1"),
                api_key=os.environ["LLM_KEY"], timeout=120, max_retries=1)
r = client.chat.completions.create(model="fast-json", max_tokens=200,
                                   response_format={"type": "json_object"},
                                   messages=[{"role": "user", "content": "Return JSON {\"summary\": \"...\"} about: hello"}])
print(r.model, r.choices[0].message.content)          # r.model = which model actually answered
emb = client.embeddings.create(model="embed", input=["hello world"])
print(len(emb.data[0].embedding))
