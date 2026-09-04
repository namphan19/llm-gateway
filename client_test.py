from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="gateway",  # must match GATEWAY_API_KEY if you set one
)

PROMPT = [{"role": "user", "content": "Say hello in Vietnamese in one sentence."}]

for model in ["local", "fast", "reasoning", "gemini", "free"]:
    print(f"\n=== {model} ===")
    try:
        # with_raw_response keeps the headers, where the gateway reports its routing
        raw = client.chat.completions.with_raw_response.create(model=model, messages=PROMPT)
        r = raw.parse()
        print(r.choices[0].message.content)
        print("served by:", raw.headers.get("x-gateway-provider"),
              "/", raw.headers.get("x-gateway-model"),
              "in", raw.headers.get("x-gateway-latency"), "s")
    except Exception as e:
        print("ERROR:", e)

print("\n=== streaming (free) ===")
try:
    for chunk in client.chat.completions.create(model="free", messages=PROMPT, stream=True):
        delta = chunk.choices[0].delta.content
        if delta:
            print(delta, end="", flush=True)
    print()
except Exception as e:
    print("ERROR:", e)
