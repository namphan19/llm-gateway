import os, time, asyncio, logging, contextlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, ConfigDict

# uvicorn does not load .env by itself; override=False keeps a real
# environment variable winning over the file.
load_dotenv(override=False)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("llm-gateway")

TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "120"))

# Optional gateway auth. Empty = open (only bind to localhost in that case).
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "").strip()


def _cloudflare_base_url() -> str:
    """Workers AI speaks OpenAI under /ai/v1; the account id is part of the path."""
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not account:
        return ""
    return f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1"


def _ollama_base_url() -> str:
    """Ollama serves the OpenAI-compatible API under /v1; tolerate a URL without it."""
    raw = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    return raw if raw.endswith("/v1") else raw + "/v1"


PROVIDERS: Dict[str, Dict[str, str]] = {
    "ollama": {
        "base_url": _ollama_base_url(),
        "api_key": os.getenv("OLLAMA_API_KEY", "ollama"),
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key": os.getenv("GEMINI_API_KEY", ""),
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": os.getenv("GROQ_API_KEY", ""),
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "api_key": os.getenv("CEREBRAS_API_KEY", ""),
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": os.getenv("OPENROUTER_API_KEY", ""),
    },
    "cloudflare": {
        "base_url": _cloudflare_base_url(),
        "api_key": os.getenv("CLOUDFLARE_API_TOKEN", ""),
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "api_key": os.getenv("MISTRAL_API_KEY", ""),
    },
    # Alibaba Model Studio. The base URL embeds the workspace id and region,
    # so it has to come from .env; keys are scoped to one workspace.
    "alibaba": {
        "base_url": os.getenv("ALIBABA_BASE_URL", "").rstrip("/"),
        "api_key": os.getenv("ALIBABA_API_KEY", ""),
    },
    # Another aggregator. Its "free" models work without credits; everything
    # else returns 402 until the account is topped up.
    "orcarouter": {
        "base_url": "https://api.orcarouter.ai/v1",
        "api_key": os.getenv("ORCAROUTER_API_KEY", ""),
    },
}

# Each alias is an ordered fallback chain of (provider, model).
# Model IDs differ per provider, so they are declared per provider: sending one
# provider's model ID to the next one is what made the old fallback useless.
# Every entry is overridable via {ALIAS}_{PROVIDER}_MODEL in .env.
# Two ordering rules: providers serving qwen3.8-27b lead, and Ollama is always
# the last hop so a cloud provider is tried before the local one.
ALIAS_DEFAULTS: Dict[str, List[Tuple[str, str]]] = {
    "local": [
        ("ollama", "gemma4:31b-cloud"),
    ],
    "fast": [
        ("groq", "qwen/qwen3.8-27b"),
        ("orcarouter", "qwen/qwen3.8-27b-free"),
        ("cloudflare", "@cf/qwen/qwen3.8-27b"),
        ("alibaba", "qwen3.8-27b"),
        ("cerebras", "gemma-4-31b"),
        ("mistral", "mistral-medium-latest"),
        ("openrouter", "nvidia/nemotron-3.5-lightning:free"),
        ("ollama", "gpt-oss:120b-cloud"),
    ],
    "reasoning": [
        ("groq", "qwen/qwen3.8-27b"),
        ("orcarouter", "qwen/qwen3.8-27b-free"),
        ("cloudflare", "@cf/qwen/qwen3.8-27b"),
        ("alibaba", "qwen3.8-27b"),
        ("cerebras", "gemma-4-31b"),
        ("mistral", "magistral-medium-latest"),
        ("openrouter", "minimax/minimax-m3:free"),
        ("gemini", "gemini-3.5-flash"),
        ("ollama", "gpt-oss:120b-cloud"),
    ],
    # qwen3.8-27b providers lead; codestral follows as the code-specialised hop.
    "coding": [
        ("groq", "qwen/qwen3.8-27b"),
        ("orcarouter", "qwen/qwen3.8-27b-free"),
        ("alibaba", "qwen3.8-27b"),
        ("mistral", "codestral-latest"),
        ("cloudflare", "@cf/qwen/qwen3.8-27b"),
        ("cerebras", "gemma-4-31b"),
        ("ollama", "gemma4:31b-cloud"),
    ],
    "gemini": [
        ("gemini", "gemini-3.5-flash"),
    ],
    "free": [
        ("orcarouter", "qwen/qwen3.8-27b-free"),
        ("groq", "qwen/qwen3.8-27b"),
        ("cloudflare", "@cf/qwen/qwen3.8-27b"),
        ("alibaba", "qwen3.8-27b"),
        ("cerebras", "gemma-4-31b"),
        ("mistral", "mistral-small-latest"),
        ("openrouter", "nvidia/nemotron-3.5-lightning:free"),
        ("gemini", "gemini-3.5-flash-lite"),
        ("ollama", "gemma4:31b-cloud"),
    ],
}


def _build_routes() -> Dict[str, List[Tuple[str, str]]]:
    return {
        alias: [
            (provider, os.getenv(f"{alias.upper()}_{provider.upper()}_MODEL", default))
            for provider, default in chain
        ]
        for alias, chain in ALIAS_DEFAULTS.items()
    }


ROUTES = _build_routes()

# Order used for a bare model ID that is neither an alias nor provider-prefixed.
DEFAULT_CHAIN = ["groq", "orcarouter", "cloudflare", "alibaba", "cerebras",
                 "mistral", "openrouter", "gemini", "ollama"]

OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"


class Message(BaseModel):
    role: str
    content: Any = None


class ChatRequest(BaseModel):
    # Unknown OpenAI fields (tools, response_format, stop, seed, ...) pass through.
    model_config = ConfigDict(extra="allow")

    model: str = "free"
    messages: List[Message]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stream: bool = False


def plan(requested: str) -> List[Tuple[str, str]]:
    """Return the ordered [(provider, model)] attempts for a requested model."""
    if requested in ROUTES:
        return list(ROUTES[requested])

    # Explicit provider:model syntax, e.g. groq:openai/gpt-oss-120b.
    # Ollama tags contain a colon too (gemma4:31b-cloud), so only split when the
    # prefix is actually a known provider.
    if ":" in requested:
        prefix, rest = requested.split(":", 1)
        if prefix in PROVIDERS:
            return [(prefix, rest)]

    return [(p, requested) for p in DEFAULT_CHAIN]


def body_for(req: ChatRequest, model: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "model": model,
        "messages": [m.model_dump(exclude_none=True) for m in req.messages],
    }
    for k in ("temperature", "max_tokens", "top_p"):
        v = getattr(req, k)
        if v is not None:
            data[k] = v
    if req.stream:
        data["stream"] = True
    data.update(req.model_extra or {})
    return data


def request_parts(provider: str, model: str, req: ChatRequest):
    cfg = PROVIDERS[provider]
    if provider != "ollama" and not cfg["api_key"]:
        raise RuntimeError(f"{provider}: API key not configured")
    if not cfg["base_url"]:
        raise RuntimeError(f"{provider}: CLOUDFLARE_ACCOUNT_ID not configured")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
        "X-Title": "Free LLM Gateway",
    }
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    return url, headers, body_for(req, model)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # One shared client so connections and TLS sessions are reused across requests.
    app.state.http = httpx.AsyncClient(timeout=TIMEOUT)
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(title="Free LLM Gateway", version="2.0.0", lifespan=lifespan)


def check_auth(authorization: Optional[str]):
    if not GATEWAY_API_KEY:
        return
    if authorization != f"Bearer {GATEWAY_API_KEY}":
        raise HTTPException(401, "Invalid gateway API key")


def gateway_headers(provider: str, model: str, elapsed: float) -> Dict[str, str]:
    # The OpenAI SDK drops unknown body fields, so the routing decision is also
    # reported in headers (readable client-side via .with_raw_response).
    return {
        "X-Gateway-Provider": provider,
        "X-Gateway-Model": model,
        "X-Gateway-Latency": f"{elapsed:.3f}",
    }


async def call_provider(provider: str, model: str, req: ChatRequest) -> JSONResponse:
    url, headers, payload = request_parts(provider, model, req)

    started = time.perf_counter()
    r = await app.state.http.post(url, headers=headers, json=payload)
    elapsed = time.perf_counter() - started

    if r.status_code >= 400:
        raise RuntimeError(f"{provider} HTTP {r.status_code}: {r.text[:500]}")

    result = r.json()
    result["_gateway"] = {
        "provider": provider,
        "model": model,
        "latency_seconds": round(elapsed, 3),
    }
    return JSONResponse(result, headers=gateway_headers(provider, model, elapsed))


async def stream_provider(provider: str, model: str, req: ChatRequest) -> StreamingResponse:
    url, headers, payload = request_parts(provider, model, req)

    started = time.perf_counter()
    ctx = app.state.http.stream("POST", url, headers=headers, json=payload)
    upstream = await ctx.__aenter__()

    # Fail before any byte reaches the client, so fallback is still possible.
    if upstream.status_code >= 400:
        body = (await upstream.aread()).decode("utf-8", "replace")[:500]
        await ctx.__aexit__(None, None, None)
        raise RuntimeError(f"{provider} HTTP {upstream.status_code}: {body}")

    async def relay():
        try:
            # aiter_bytes, not aiter_raw: some providers (Gemini) gzip the SSE
            # stream, and the Content-Encoding header is not forwarded, so the
            # body has to be decompressed here.
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await ctx.__aexit__(None, None, None)

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers=gateway_headers(provider, model, time.perf_counter() - started),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "free-llm-gateway"}


# Some clients (GitHub Copilot custom endpoints among them) append the path to
# a base URL that may or may not already carry /v1, so both forms are served.
@app.get("/v1/models")
@app.get("/models")
async def models(authorization: Optional[str] = Header(default=None)):
    check_auth(authorization)
    data: List[Dict[str, Any]] = [
        {
            "id": alias,
            "object": "model",
            "owned_by": "free-llm-gateway",
            "route": [{"provider": p, "model": m} for p, m in chain],
        }
        for alias, chain in ROUTES.items()
    ]
    data += [{"id": f"{p}:<model>", "object": "model", "owned_by": p} for p in PROVIDERS]
    return {"object": "list", "data": data}


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat(req: ChatRequest, authorization: Optional[str] = Header(default=None)):
    check_auth(authorization)

    errors = []
    for provider, model in plan(req.model):
        try:
            if req.stream:
                response = await stream_provider(provider, model, req)
            else:
                response = await call_provider(provider, model, req)
            log.info("request model=%s -> provider=%s model=%s", req.model, provider, model)
            return response
        except Exception as e:
            errors.append({"provider": provider, "model": model, "error": str(e)})
            log.warning("provider=%s model=%s failed: %s", provider, model, e)

    raise HTTPException(
        status_code=503,
        detail={"message": "All candidate providers failed", "errors": errors},
    )


# ---------------------------------------------------------------- quota ----
# Only three providers report quota, and none of them do it on /models, so a
# probe costs one real (1-token) chat request. Gemini and Ollama expose nothing.
RATE_HEADERS = {
    "groq": [
        # (label, window, limit header, remaining header, reset header)
        ("Requests", None, "x-ratelimit-limit-requests",
         "x-ratelimit-remaining-requests", "x-ratelimit-reset-requests"),
        ("Tokens", None, "x-ratelimit-limit-tokens",
         "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens"),
    ],
    "mistral": [
        ("Requests", "minute", "x-ratelimit-limit-req-minute",
         "x-ratelimit-remaining-req-minute", None),
        ("Tokens", "minute", "x-ratelimit-limit-tokens-minute",
         "x-ratelimit-remaining-tokens-minute", None),
    ],
    "cerebras": [
        (kind.title(), window,
         f"x-ratelimit-limit-{kind}-{window}",
         f"x-ratelimit-remaining-{kind}-{window}", None)
        for kind in ("requests", "tokens")
        for window in ("minute", "hour", "day")
    ],
}


def probe_model(provider: str) -> Optional[str]:
    """Cheapest known-good model for a provider, taken from the routing table."""
    for chain in ROUTES.values():
        for p, model in chain:
            if p == provider:
                return model
    return None


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def quota_from_headers(provider: str) -> Dict[str, Any]:
    model = probe_model(provider)
    if model is None:
        return {"status": "unsupported", "detail": "No model configured"}

    req = ChatRequest(model=model, messages=[Message(role="user", content="hi")],
                      max_tokens=1)
    url, headers, payload = request_parts(provider, model, req)
    r = await app.state.http.post(url, headers=headers, json=payload)

    limits = []
    for label, window, h_limit, h_remaining, h_reset in RATE_HEADERS[provider]:
        limit = _int(r.headers.get(h_limit))
        remaining = _int(r.headers.get(h_remaining))
        if limit is None and remaining is None:
            continue
        # Cerebras sometimes reports remaining > limit for the hour window; the
        # two headers disagree upstream, so report both and skip the derived use.
        used = None
        if limit is not None and remaining is not None and remaining <= limit:
            used = limit - remaining
        limits.append({
            "label": label,
            "window": window,
            "limit": limit,
            "remaining": remaining,
            "used": used,
            "reset": r.headers.get(h_reset) if h_reset else None,
        })

    if r.status_code >= 400 and not limits:
        return {"status": "error", "detail": f"HTTP {r.status_code}: {r.text[:200]}"}
    return {
        "status": "ok" if r.status_code < 400 else "limited",
        "detail": None if r.status_code < 400 else f"HTTP {r.status_code}",
        "probe_model": model,
        "limits": limits,
    }


async def quota_openrouter() -> Dict[str, Any]:
    # OpenRouter is the one provider with a dedicated endpoint, so no chat call.
    r = await app.state.http.get(
        OPENROUTER_KEY_URL,
        headers={"Authorization": f"Bearer {PROVIDERS['openrouter']['api_key']}"},
    )
    if r.status_code >= 400:
        return {"status": "error", "detail": f"HTTP {r.status_code}: {r.text[:200]}"}

    d = r.json().get("data", {})
    limits = [{
        "label": "Credit used",
        "window": "total",
        "limit": d.get("limit"),
        "remaining": d.get("limit_remaining"),
        "used": d.get("usage"),
        "unit": "USD",
        "reset": d.get("limit_reset"),
    }]
    for window in ("daily", "weekly", "monthly"):
        limits.append({
            "label": f"Spend {window}", "window": window, "limit": None,
            "remaining": None, "used": d.get(f"usage_{window}"), "unit": "USD",
            "reset": None,
        })
    return {
        "status": "ok",
        "detail": "Free tier" if d.get("is_free_tier") else "Paid",
        "probe_model": None,
        "limits": limits,
    }


async def quota_reachable(provider: str) -> Dict[str, Any]:
    """Gemini and Ollama publish no quota at all, so only report reachability."""
    model = probe_model(provider)
    if model is None:
        return {"status": "unsupported", "detail": "No model configured"}
    req = ChatRequest(model=model, messages=[Message(role="user", content="hi")],
                      max_tokens=1)
    url, headers, payload = request_parts(provider, model, req)
    r = await app.state.http.post(url, headers=headers, json=payload)
    if r.status_code >= 400:
        return {"status": "error", "detail": f"HTTP {r.status_code}: {r.text[:200]}",
                "probe_model": model, "limits": []}

    # Workers AI prices each call in "neurons" but never says how many are left,
    # so report the cost of this call rather than a remaining balance.
    limits = []
    neurons = r.headers.get("cf-ai-neurons")
    if neurons:
        limits.append({"label": "Neurons / request", "window": "per call",
                       "limit": None, "remaining": None, "used": float(neurons),
                       "unit": "neurons", "reset": None})
        detail = "Chỉ báo chi phí mỗi request, không báo số còn lại"
    else:
        detail = "Provider reports no quota"
    return {"status": "reachable", "detail": detail,
            "probe_model": model, "limits": limits}


async def quota_for(provider: str) -> Dict[str, Any]:
    cfg = PROVIDERS[provider]
    if provider != "ollama" and not cfg["api_key"]:
        return {"provider": provider, "status": "no_key",
                "detail": "API key not configured", "limits": []}
    try:
        if provider == "openrouter":
            result = await quota_openrouter()
        elif provider in RATE_HEADERS:
            result = await quota_from_headers(provider)
        else:
            result = await quota_reachable(provider)
    except Exception as e:
        result = {"status": "error", "detail": str(e)[:200], "limits": []}
    return {"provider": provider, **result}


@app.get("/quota")
async def quota(authorization: Optional[str] = Header(default=None)):
    check_auth(authorization)
    started = time.perf_counter()
    results = await asyncio.gather(*(quota_for(p) for p in PROVIDERS))
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "providers": list(results),
    }


# ------------------------------------------------------- Anthropic API ----
# Claude Code talks the Anthropic Messages API, not chat/completions. Probing
# every provider showed three serve /messages natively (Ollama, OpenRouter,
# OrcaRouter), so requests are proxied untouched — no format translation.
# Cloudflare exposes the endpoint but allows it for no model on this account;
# Groq, Cerebras, Mistral and Gemini return 404.
ANTHROPIC_PROVIDERS = {"ollama", "openrouter", "orcarouter"}

# Derived from the chat routing so the two sides cannot drift apart.
ANTHROPIC_ROUTES = {
    alias: hops
    for alias, chain in ROUTES.items()
    if (hops := [(p, m) for p, m in chain if p in ANTHROPIC_PROVIDERS])
}


def anthropic_plan(requested: str) -> List[Tuple[str, str]]:
    if requested in ANTHROPIC_ROUTES:
        return list(ANTHROPIC_ROUTES[requested])
    if ":" in requested:
        prefix, rest = requested.split(":", 1)
        if prefix in ANTHROPIC_PROVIDERS:
            return [(prefix, rest)]
    # A bare Claude model name (Claude Code sends its own) goes down the chain.
    return list(ANTHROPIC_ROUTES.get("coding", []))


def anthropic_parts(provider: str, model: str, body: Dict[str, Any]):
    cfg = PROVIDERS[provider]
    if provider != "ollama" and not cfg["api_key"]:
        raise RuntimeError(f"{provider}: API key not configured")

    payload = dict(body)
    payload["model"] = model
    headers = {
        "Content-Type": "application/json",
        "x-api-key": cfg["api_key"],
        "authorization": f"Bearer {cfg['api_key']}",
        "anthropic-version": "2023-06-01",
        "X-Title": "Free LLM Gateway",
    }
    return cfg["base_url"].rstrip("/") + "/messages", headers, payload


@app.post("/v1/messages")
@app.post("/messages")
async def messages(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    # Claude Code authenticates with x-api-key; accept either header.
    check_auth(authorization or (f"Bearer {x_api_key}" if x_api_key else None))

    requested = str(body.get("model", "coding"))
    streaming = bool(body.get("stream"))
    errors = []

    for provider, model in anthropic_plan(requested):
        try:
            url, headers, payload = anthropic_parts(provider, model, body)
            started = time.perf_counter()

            if streaming:
                ctx = app.state.http.stream("POST", url, headers=headers, json=payload)
                upstream = await ctx.__aenter__()
                if upstream.status_code >= 400:
                    detail = (await upstream.aread()).decode("utf-8", "replace")[:500]
                    await ctx.__aexit__(None, None, None)
                    raise RuntimeError(f"{provider} HTTP {upstream.status_code}: {detail}")

                async def relay(ctx=ctx, upstream=upstream):
                    try:
                        async for chunk in upstream.aiter_bytes():
                            yield chunk
                    finally:
                        await ctx.__aexit__(None, None, None)

                response = StreamingResponse(
                    relay(), media_type="text/event-stream",
                    headers=gateway_headers(provider, model, time.perf_counter() - started),
                )
            else:
                r = await app.state.http.post(url, headers=headers, json=payload)
                elapsed = time.perf_counter() - started
                if r.status_code >= 400:
                    raise RuntimeError(f"{provider} HTTP {r.status_code}: {r.text[:500]}")
                response = JSONResponse(r.json(),
                                        headers=gateway_headers(provider, model, elapsed))

            log.info("messages model=%s -> provider=%s model=%s", requested, provider, model)
            return response
        except Exception as e:
            errors.append({"provider": provider, "model": model, "error": str(e)})
            log.warning("messages provider=%s model=%s failed: %s", provider, model, e)

    raise HTTPException(
        status_code=503,
        detail={"message": "All candidate providers failed", "errors": errors},
    )


@app.get("/")
async def dashboard():
    return FileResponse(Path(__file__).parent / "dashboard.html")
