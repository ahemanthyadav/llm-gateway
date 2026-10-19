// Node 18+ — standard OpenAI SDK (npm i openai). No gateway-specific code.
import OpenAI from "openai";
const client = new OpenAI({ baseURL: process.env.LLM_URL ?? "http://llm-gateway.llm.svc.cluster.local:4000/v1",
                            apiKey: process.env.LLM_KEY });
const r = await client.chat.completions.create({ model: "general", max_tokens: 200,
  messages: [{ role: "user", content: "One sentence about the weather." }] });
console.log(r.model, r.choices[0].message.content);
