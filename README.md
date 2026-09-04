# Free LLM Gateway

A small OpenAI-compatible gateway that aggregates:

- Ollama (local, including Ollama cloud models)
- Google Gemini API
- Groq
- Cerebras
- OpenRouter free models
- Cloudflare Workers AI
- Mistral
- Alibaba Model Studio
- OrcaRouter free models

The gateway provides one endpoint:

`http://localhost:8000/v1/chat/completions`

Full usage guide (Vietnamese): [USAGE.md](USAGE.md)

## Routing

Logical model aliases. Each alias is an ordered fallback chain, and **each hop
carries its own model ID** — provider model IDs are not interchangeable, so the
chain declares one per provider:

| Alias | Chain (provider → model) |
|---|---|
| `local` | ollama `gemma4:31b-cloud` |
| `fast` | groq `qwen/qwen3.8-27b` → orcarouter → cloudflare → alibaba → cerebras → mistral → openrouter → ollama |
| `reasoning` | groq `qwen/qwen3.8-27b` → orcarouter → cloudflare → alibaba → cerebras → mistral → openrouter → gemini → ollama |
| `coding` | groq `qwen/qwen3.8-27b` → orcarouter → alibaba `qwen3.8-27b` → mistral `codestral-latest` → cloudflare `@cf/qwen/qwen3.8-27b` → cerebras → ollama |
| `gemini` | gemini `gemini-3.5-flash` |
| `free` | orcarouter `qwen/qwen3.8-27b-free` → groq → cloudflare → alibaba → cerebras → mistral → openrouter → gemini → ollama |

Two ordering rules: the providers that serve **qwen3.8-27b** (Groq, OrcaRouter,
Cloudflare, Alibaba) lead every chain, and **Ollama is always the last hop** so a cloud
provider is tried before the local one.

Watch the provider ids: `orcarouter` is a different service from `openrouter`.

The gateway falls back to the next hop when a provider is unavailable,
rate-limited, or has no API key configured.

Every model in every chain is overridable from `.env` using
`{ALIAS}_{PROVIDER}_MODEL`, e.g. `FREE_GROQ_MODEL=llama-3.3-70b-versatile`.
See [.env.example](.env.example); the defaults live in [app/main.py](app/main.py).

You can also force a single provider with `provider:model`:

- `groq:openai/gpt-oss-120b`
- `cerebras:gemma-4-31b`
- `openrouter:nvidia/nemotron-3.5-lightning:free`
- `cloudflare:@cf/qwen/qwen3.8-27b`
- `mistral:mistral-medium-latest`
- `alibaba:qwen3.8-27b`
- `orcarouter:orcarouter/free`
- `ollama:gemma4:31b-cloud`

Only the first colon is split, and only when the prefix is a known provider, so
Ollama tags that contain a colon work as expected.

`GET /v1/models` lists the aliases together with their resolved chains.

## Quota dashboard

`GET /` serves a dashboard showing each provider's remaining limits; `GET /quota`
returns the same data as JSON. Cerebras reports requests and tokens per
minute/hour/day, Groq reports both plus reset times, Mistral reports both per
minute, OpenRouter reports spend.
Cloudflare reports the neuron cost of each call but not the balance left. Gemini
and Ollama publish no quota at all, so they only show reachability.

Neither Groq nor Cerebras exposes rate-limit headers on `/models`, so a check
costs one real 1-token request per provider. OpenRouter has a dedicated
`/api/v1/key` endpoint and costs nothing.

## Which provider answered?

The gateway reports its routing decision two ways:

- response headers `X-Gateway-Provider`, `X-Gateway-Model`, `X-Gateway-Latency`
- a `_gateway` object in the JSON body (non-streaming only)

Prefer the headers from the OpenAI SDK — the SDK drops unknown body fields.

## Anthropic API (Claude Code)

`POST /v1/messages` (and `/messages`) serves the Anthropic Messages API, so
Claude Code can point at the gateway with `ANTHROPIC_BASE_URL`.

Probing every provider showed three speak it natively — Ollama, OpenRouter and
OrcaRouter — so requests are proxied untouched, with no format translation.
Cloudflare exposes the endpoint but permits it for no model on this account;
Groq, Cerebras, Mistral and Gemini return 404.

The Anthropic chains are filtered from the chat chains, so the two cannot drift.

## Client path compatibility

Both `/v1/chat/completions` and `/chat/completions` are served (same for
`/models`), because clients that build a URL from a configured base — GitHub
Copilot custom endpoints among them — differ on whether they append `/v1`.

## Streaming

`stream: true` is supported and passed through as SSE. Fallback still applies:
a provider that fails before the first byte is skipped, and the next hop is
tried instead.

## Auth

Set `GATEWAY_API_KEY` in `.env` to require `Authorization: Bearer <key>` from
clients. Leave it empty to accept any key — only do that while the gateway is
bound to localhost.

## Running it (Windows)

Make sure Ollama is up first:

```powershell
ollama serve
ollama list
```

Then, once:

```powershell
copy .env.example .env    # fill in whatever API keys you have
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

And to start the gateway:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

`.env` is read automatically (python-dotenv), so no environment setup is
needed. Add `--reload` while editing the code. Stop with Ctrl+C.

Check it:

```powershell
curl http://localhost:8000/health
```

`OLLAMA_BASE_URL` defaults to `http://localhost:11434`; the `/v1` suffix is
optional, the gateway appends it.

## Test chat

```powershell
curl http://localhost:8000/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d '{"model":"free","messages":[{"role":"user","content":"Say hi in Vietnamese"}]}'
```

## Python / OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="gateway",  # must match GATEWAY_API_KEY if you set one
)

raw = client.chat.completions.with_raw_response.create(
    model="free",
    messages=[{"role": "user", "content": "Explain LoRA briefly."}],
)
r = raw.parse()

print(r.choices[0].message.content)
print("served by:", raw.headers.get("x-gateway-provider"), raw.headers.get("x-gateway-model"))
```

Run [client_test.py](client_test.py) to exercise every alias plus streaming.

## LangChain

Use the OpenAI-compatible endpoint:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    api_key="gateway",
    model="free",
)

print(llm.invoke("Explain RAG in 3 bullets.").content)
```

## Important

Free-tier limits and available models change. Keep provider-specific model IDs
in `.env` so you can change them without touching application code.

Gemini retires model IDs without warning — `gemini-2.5-flash` and
`gemini-2.5-pro` now return HTTP 404 ("no longer available"), and the `pro`
tiers return 429 on the free quota. `gemini-3.5-flash` and
`gemini-3.5-flash-lite` are the ones this config uses.

Groq serves `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`,
`groq/compound`, `groq/compound-mini` and `allam-2-7b` for chat; the whisper,
orpheus and prompt-guard entries in `GET /v1/models` are audio/classifier
models and will not answer chat requests. `qwen/qwen3.6-27b` leaks its
`<think>` block into `content`, so it is not used here.

OpenRouter `:free` models come from a shared upstream pool and return HTTP 429
("temporarily rate-limited upstream") fairly often, and slugs get retired
(`meta-llama/llama-3.3-70b-instruct:free` and `deepseek/deepseek-r1:free` are
already gone). `GET https://openrouter.ai/api/v1/models` lists what is live.
The fallback chain absorbs both cases.

Ollama cloud models are billed against your ollama.com plan — some return
HTTP 402 unless you upgrade. `ollama list` shows what you have pulled;
whether a model is *usable* only shows up on the first request.

For research involving sensitive data, review each provider's data-use policy
before sending data. Gemini's current free developer tier states that content
may be used to improve Google's products; paid tiers have different data-use
terms.
