# Hướng dẫn sử dụng — Free LLM Gateway

Gateway gom nhiều nhà cung cấp LLM miễn phí về **một endpoint duy nhất** tương
thích OpenAI. Bạn viết code một lần, gọi model bằng tên logic (`fast`,
`reasoning`, `free`…), gateway tự chọn nhà cung cấp và tự chuyển sang nhà khác
khi nhà hiện tại lỗi, hết quota hoặc chưa có key.

```
Client (OpenAI SDK / LangChain / curl)
        ↓  http://localhost:8000/v1/chat/completions
    Gateway  ──►  Ollama · Groq · Cerebras · OpenRouter · Gemini · Cloudflare · Mistral · OrcaRouter · Alibaba
```

---

## 1. Yêu cầu

| Thành phần | Ghi chú |
|---|---|
| Python 3.12+ | Đã kiểm trên 3.14.6 |
| Ollama | Tuỳ chọn, nhưng nên có — chạy local, nhanh nhất, không cần key |
| API key | Tuỳ chọn, có cái nào dùng cái đó |

Không cần key nào cũng chạy được, miễn có Ollama.

---

## 2. Cài đặt (làm một lần)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

---

## 3. Cấu hình `.env`

Mở `.env`, điền key nào bạn có. **Bỏ trống cũng được** — gateway tự bỏ qua nhà
cung cấp không có key.

```ini
OLLAMA_BASE_URL=http://localhost:11434

GEMINI_API_KEY=
GROQ_API_KEY=
CEREBRAS_API_KEY=
OPENROUTER_API_KEY=
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
ALIBABA_BASE_URL=
ALIBABA_API_KEY=
MISTRAL_API_KEY=
```

Lấy key ở đâu:

| Nhà cung cấp | Trang tạo key | Lưu ý |
|---|---|---|
| Groq | <https://console.groq.com/keys> | Đăng nhập bằng Google/GitHub |
| Cerebras | <https://cloud.cerebras.ai> | Phải bật billing, nếu không sẽ lỗi 402 |
| OpenRouter | <https://openrouter.ai/keys> | Free tier có giới hạn số request/ngày |
| Gemini | <https://aistudio.google.com/apikey> | Free tier chặn các model `pro` |
| Cloudflare | <https://dash.cloudflare.com/profile/api-tokens> | Cần cả **Account ID** lẫn token, xem Workers AI |
| OrcaRouter | <https://www.orcarouter.ai/console> | Aggregator 191 model; chỉ các model `*-free` chạy khi chưa nạp. Id là `orcarouter`, dễ nhầm với `openrouter` |
| Alibaba Model Studio | <https://bailian.console.aliyun.com> | 165 model. Key gắn theo **workspace + region**; `ALIBABA_BASE_URL` phải chứa cả hai |
| Mistral | <https://console.mistral.ai/api-keys> | Tier free chặn `mistral-large`; tránh `ministral-3b` |
| Ollama | không cần | Cài từ <https://ollama.com> |

> `.env` đã nằm trong `.gitignore`. Đừng bao giờ commit nó, và đừng điền key
> thật vào `.env.example`.

---

## 4. Khởi chạy

Bật Ollama trước (nếu dùng):

```powershell
ollama serve
```

Rồi chạy gateway:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

`.env` được nạp tự động. Thêm `--reload` khi đang sửa code. Dừng bằng `Ctrl+C`.

Kiểm tra:

```powershell
curl http://localhost:8000/health
```

Kết quả mong đợi: `{"status":"ok","service":"free-llm-gateway"}`

---

## 4b. Bảng theo dõi quota

Mở <http://localhost:8000> trong trình duyệt để xem hạn mức còn lại của từng
nhà cung cấp. Dữ liệu thô có ở `GET /quota`.

| Nhà cung cấp | Báo được gì |
|---|---|
| Cerebras | Requests và tokens theo phút / giờ / ngày |
| Groq | Requests và tokens, kèm thời điểm reset |
| OpenRouter | Chi tiêu tích luỹ, theo ngày / tuần / tháng |
| Mistral | Requests và tokens theo **phút** |
| Cloudflare | Chi phí **neurons** mỗi request — không báo số còn lại |
| Gemini | Không công bố — chỉ xác nhận gọi được |
| OrcaRouter | Chỉ có cờ `X-Credits-Low`, không có số liệu |
| Alibaba | Không công bố header quota |
| Ollama | **Session + weekly (%) và số request từng model** — cần `OLLAMA_API_KEY` |

> Groq và Cerebras chỉ trả hạn mức **kèm theo một request thật**, không có ở
> `/models`. Nên mỗi lần bấm "Kiểm tra lại" tốn 1 request (1 token) của mỗi
> nhà đó. OpenRouter đọc từ endpoint riêng nên không tốn gì.

Nếu bạn đã bật `GATEWAY_API_KEY`, trang sẽ hiện ô nhập key.

---

## 4c. Triển khai lên máy production

Model Ollama của bạn đều là **cloud** — chúng chỉ nặng vài trăm byte (manifest),
không có trọng số, và `remote_host` trỏ về `ollama.com`. Nói cách khác Ollama
trên máy dev chỉ là một proxy có xác thực. Có ba cách đưa lên server.

### Cách 1 — Trỏ thẳng vào API của ollama.com (khuyên dùng)

Không cài gì trên server. Lấy API key tại <https://ollama.com/settings/keys>,
rồi trong `.env` của production:

```ini
OLLAMA_BASE_URL=https://ollama.com/v1
OLLAMA_API_KEY=<key cua ban>

# Model bo hau to -cloud
LOCAL_OLLAMA_MODEL=gemma4:31b
FAST_OLLAMA_MODEL=gpt-oss:120b
REASONING_OLLAMA_MODEL=gpt-oss:120b
FREE_OLLAMA_MODEL=gemma4:31b
CODING_OLLAMA_MODEL=gemma4:31b
```

API giữ nguyên hoàn toàn, alias `local` vẫn chạy, không cần daemon nào. Tên model
bỏ hậu tố `-cloud` vì đó là quy ước của client Ollama, không phải của API.

`ollama.com/v1` liệt kê 19 model, nhưng **gói của bạn chỉ mở 2 cái**:

| Model | Latency | |
|---|---|---|
| `gpt-oss:120b` | 0.86–1.08s | ✅ |
| `gemma4:31b` | 1.36–1.41s | ✅ |
| `glm-5.3`, `kimi-k3`, `qwen3.5:397b`… | — | ❌ *"requires a subscription or extra usage"* |

Giống hệt các model `:cloud` trên máy dev: chỉ `gemma4:31b-cloud` và
`gpt-oss:120b-cloud` chạy, các cái khác trả 402.

`https://ollama.com/v1/messages` **cũng nói chuẩn Anthropic**, nên Claude Code
vẫn hoạt động ở chế độ production.

### Xem usage của Ollama

`https://ollama.com/api/usage` trả về mức dùng thật. Chỉ cần đặt
`OLLAMA_API_KEY`, gateway sẽ đọc và hiện lên dashboard — **kể cả khi chat vẫn đi
qua daemon local**, vì cả hai đường đều tiêu quota của cùng một tài khoản.

```
Ollama                                  ĐANG HOẠT ĐỘNG
Tuần này: web search ×6, gemma4:31b ×189, gpt-oss:120b ×176

Session  SESSION      0.1% / 100
Weekly   WEEK        16.1% / 100
```

Daemon local (`localhost:11434/api/usage`) trả 404 — endpoint này chỉ có trên
ollama.com.

### Cách 2 — Cài Ollama trên server

Nếu bạn muốn giữ đúng daemon Ollama:

1. Cài Ollama trên server
2. Chép `~/.ollama/id_ed25519` và `id_ed25519.pub` từ máy dev sang server —
   đây là khoá xác thực với tài khoản ollama.com
3. `ollama pull gemma4:31b-cloud` (chỉ tải manifest, vài trăm byte)
4. `.env` giữ nguyên `OLLAMA_BASE_URL=http://localhost:11434`

Đổi lại bạn phải chạy và giám sát thêm một tiến trình, và cùng một khoá tài
khoản nằm trên hai máy.

### Cách 3 — Bỏ hẳn Ollama

```ini
DISABLED_PROVIDERS=ollama
```

Provider bị tắt biến mất khỏi mọi chuỗi fallback, khỏi `/v1/models` và `/quota`.
Ngăn cách bằng dấu phẩy nếu tắt nhiều: `ollama,gemini`.

Lưu ý alias `local` sẽ trả 503 kèm lý do rõ ràng, vì nó chỉ có mỗi Ollama:

```json
{"detail": "Alias 'local' has no provider left: every hop is in DISABLED_PROVIDERS"}
```

Các alias khác không bị ảnh hưởng — chúng chỉ mất chặng cuối.

### So sánh

| | Cách 1 (ollama.com) | Cách 2 (cài Ollama) | Cách 3 (tắt) |
|---|---|---|---|
| Cài trên server | không | có | không |
| API giữ nguyên | ✅ | ✅ | ⚠️ mất `local` |
| Sửa `.env` | base URL + key + tên model | không | 1 dòng |
| Cần chép khoá | không | có | không |

> Khi `OLLAMA_BASE_URL` không phải localhost, gateway **bắt buộc** phải có
> `OLLAMA_API_KEY`, nếu thiếu sẽ báo `ollama: API key not configured` ngay thay
> vì để ollama.com trả 401 khó hiểu.

---

## 5. Chọn model

Gọi bằng **alias logic**, đừng gọi thẳng tên model — alias tự fallback:

| Alias | Chuỗi ưu tiên | Dùng khi |
|---|---|---|
| `local` | Ollama | Riêng tư, không ra Internet |
| `fast` | Groq → OrcaRouter → Cloudflare → Alibaba → Cerebras → Mistral → OpenRouter → Ollama | Tương tác nhanh |
| `reasoning` | Groq → OrcaRouter → Cloudflare → Alibaba → Cerebras → Mistral → OpenRouter → Gemini → Ollama | Bài cần suy luận |
| `coding` | Groq → OrcaRouter → Alibaba → Mistral → Cloudflare → Cerebras → Ollama | Sinh và sửa code; chặng Mistral dùng model **chuyên code** `codestral-latest` |
| `gemini` | Gemini | Bắt buộc dùng Google |
| `free` | OrcaRouter → Groq → Cloudflare → Alibaba → Cerebras → Mistral → OpenRouter → Gemini → Ollama | Ưu tiên model miễn phí |

Hai nguyên tắc sắp thứ tự: **provider có `qwen3.8-27b`** (Groq, OrcaRouter,
Cloudflare, Alibaba) đứng đầu mọi chuỗi, và **Ollama luôn là chặng cuối** — thử nhà cung
cấp cloud trước, chỉ dùng máy mình khi tất cả đều hỏng.

Xem chuỗi thực tế đang áp dụng:

```powershell
curl http://localhost:8000/v1/models
```

### Ép một nhà cung cấp cụ thể

Cú pháp `provider:model` — bỏ qua toàn bộ fallback:

```
groq:openai/gpt-oss-120b
cerebras:gemma-4-31b
gemini:gemini-3.5-flash-lite
openrouter:minimax/minimax-m3:free
cloudflare:@cf/qwen/qwen3.8-27b
mistral:mistral-medium-latest
alibaba:qwen3.8-27b
orcarouter:orcarouter/free
ollama:gemma4:31b-cloud
```

Chỉ dấu `:` **đầu tiên** được tách, và chỉ khi tiền tố là tên nhà cung cấp hợp
lệ — nên tag Ollama có sẵn dấu `:` vẫn hoạt động bình thường.

---

## 6. Gọi gateway

### curl (PowerShell)

```powershell
curl http://localhost:8000/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d '{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"Giải thích RAG\"}]}'
```

### OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="gateway")

r = client.chat.completions.create(
    model="fast",
    messages=[{"role": "user", "content": "Giải thích LoRA ngắn gọn."}],
)
print(r.choices[0].message.content)
```

`api_key` là chuỗi bất kỳ, trừ khi bạn đã bật `GATEWAY_API_KEY` (xem mục 9).

### LangChain

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    base_url="http://localhost:8000/v1",
    api_key="gateway",
    model="reasoning",
)
print(llm.invoke("Giải thích RAG trong 3 gạch đầu dòng.").content)
```

### GitHub Copilot (custom endpoint)

Copilot nối path vào `url` bạn khai báo, và không có tài liệu nào nói rõ nó nối
`/chat/completions` hay `/v1/chat/completions`. Gateway phục vụ **cả hai**, nên
điền kiểu nào cũng chạy.

```jsonc
{
  "apiKey": "gateway",              // chuoi bat ky khi GATEWAY_API_KEY trong
  "apiType": "chat-completions",
  "models": [
    {
      "id": "coding",               // alias cua gateway, khong phai ten model
      "name": "Gateway coding",
      "maxInputTokens": 128000,
      "maxOutputTokens": 16000,
      "toolCalling": true,
      "vision": true,
      "url": "http://localhost:8000"
    }
  ],
  "name": "LLM Gateway",
  "vendor": "customendpoint"
}
```

Thêm một mục `models` nữa cho mỗi alias bạn muốn thấy trong Copilot (`fast`,
`reasoning`, `free`…) — chỉ đổi `id` và `name`.

Nếu Copilot không chấp nhận `http://localhost`, mở tunnel rồi dùng URL đó, và
**nhớ đặt `GATEWAY_API_KEY`** trước khi mở (xem mục 9).

### Claude Code (chuẩn Anthropic)

Claude Code nói **Anthropic Messages API**, không phải chat/completions. Gateway
phục vụ luôn `POST /v1/messages` (và `/messages`).

```powershell
$env:ANTHROPIC_BASE_URL = "http://localhost:8000"
$env:ANTHROPIC_AUTH_TOKEN = "gateway"     # phai khop GATEWAY_API_KEY neu ban bat
claude
```

Ba nhà cung cấp nói chuẩn Anthropic **nguyên bản**, nên request được chuyển tiếp
y nguyên — gateway không dịch định dạng, không mất mát gì:

| Alias | Chuỗi Anthropic |
|---|---|
| `coding` | OrcaRouter → Ollama |
| `fast` / `reasoning` / `free` | OrcaRouter → OpenRouter → Ollama |
| `local` | Ollama |
| `gemini` | *(không có — Gemini không hỗ trợ)* |

Chuỗi này được **lọc tự động** từ chuỗi chat, giữ lại các chặng nói được Anthropic,
nên hai bên không bao giờ lệch nhau.

Claude Code gửi tên model Claude thật (`claude-sonnet-4-5-...`). Gateway không
nhận ra tên đó nên dùng chuỗi của alias `coding`. Muốn ép alias khác thì đặt
`ANTHROPIC_MODEL` thành `fast`, `free`… hoặc `provider:model`.

Streaming hoạt động đầy đủ với đúng các event Anthropic: `message_start`,
`content_block_start`, `content_block_delta`, `content_block_stop`,
`message_delta`, `message_stop`.

### Streaming

```python
for chunk in client.chat.completions.create(
    model="fast",
    messages=[{"role": "user", "content": "Đếm từ 1 đến 10"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

Fallback vẫn hoạt động khi streaming: nhà cung cấp lỗi **trước byte đầu tiên**
sẽ bị bỏ qua và gateway chuyển sang nhà kế tiếp.

---

## 7. Biết nhà cung cấp nào đã trả lời

Gateway báo qua **header** (dùng cách này với OpenAI SDK, vì SDK loại bỏ field
lạ trong body):

```python
raw = client.chat.completions.with_raw_response.create(model="fast", messages=[...])
r = raw.parse()

print(raw.headers["x-gateway-provider"])   # groq
print(raw.headers["x-gateway-model"])      # openai/gpt-oss-120b
print(raw.headers["x-gateway-latency"])    # 0.902
```

Với curl, body cũng có sẵn (chỉ khi không streaming):

```json
"_gateway": {"provider": "groq", "model": "openai/gpt-oss-120b", "latency_seconds": 0.902}
```

Log của gateway ghi rõ từng bước fallback:

```
WARNING  provider=groq model=... failed: groq: API key not configured
INFO     request model=free -> provider=ollama model=gemma4:31b-cloud
```

---

## 8. Đổi model

Sửa trong `.env`, **không cần đụng code**. Định dạng: `{ALIAS}_{PROVIDER}_MODEL`

```ini
FAST_GROQ_MODEL=qwen/qwen3.8-27b
REASONING_GEMINI_MODEL=gemini-3.5-flash
FREE_OPENROUTER_MODEL=nvidia/nemotron-3.5-lightning:free
```

Giá trị mặc định nằm trong `ALIAS_DEFAULTS` ở `app/main.py`.

**Cách tìm model còn sống** — model miễn phí bị khai tử rất thường xuyên:

```powershell
curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $env:GROQ_API_KEY"
curl https://api.cerebras.ai/v1/models -H "Authorization: Bearer $env:CEREBRAS_API_KEY"
curl https://api.mistral.ai/v1/models -H "Authorization: Bearer $env:MISTRAL_API_KEY"
curl https://openrouter.ai/api/v1/models
curl "https://api.cloudflare.com/client/v4/accounts/$env:CLOUDFLARE_ACCOUNT_ID/ai/models/search?task=Text%20Generation" `
  -H "Authorization: Bearer $env:CLOUDFLARE_API_TOKEN"
curl https://generativelanguage.googleapis.com/v1beta/openai/models -H "Authorization: Bearer $env:GEMINI_API_KEY"
```

Lưu ý: có tên trong danh sách **không** đồng nghĩa với dùng được. Model vẫn có
thể trả 402 (cần trả phí), 429 (hết quota) hoặc chỉ hỗ trợ audio/ảnh. Cách duy
nhất để chắc chắn là gửi thử một request chat thật.

---

## 9. Bật xác thực

Mặc định gateway nhận mọi `api_key` — **chỉ an toàn khi bind vào localhost**.
Nếu mở ra ngoài, đặt trong `.env`:

```ini
GATEWAY_API_KEY=chuoi-bi-mat-cua-ban
```

Client phải gửi `Authorization: Bearer chuoi-bi-mat-cua-ban`, sai sẽ nhận 401.

Để trống thì gateway nhận mọi key — tiện khi phát triển trên localhost, nhưng
**phải đặt trước khi mở ra Internet**.

Sinh key ngẫu nhiên:

```powershell
.\.venv\Scripts\python.exe -c "import secrets;print(secrets.token_urlsafe(32))"
```

Khi bật, các endpoint được bảo vệ như sau:

| Endpoint | Cần key |
|---|---|
| `POST /v1/chat/completions` | ✅ |
| `GET /v1/models` | ✅ |
| `GET /quota` | ✅ |
| `GET /` (dashboard) | ❌ — chỉ là HTML, dữ liệu vẫn cần key |
| `GET /health` | ❌ — để health check hoạt động |

### Mở ra Internet bằng Cloudflare Tunnel

```powershell
.\cloudflared.exe tunnel --url http://localhost:8000
```

Lệnh này in ra một URL `*.trycloudflare.com` công khai. Không cần tài khoản
Cloudflare, không cần mở port trên router, và gateway vẫn chỉ bind vào
`127.0.0.1` — cloudflared kết nối từ bên trong máy ra.

> **Bắt buộc đặt `GATEWAY_API_KEY` trước khi làm việc này.** URL của quick
> tunnel không có lớp xác thực nào của riêng nó; ai có link là gọi được, và mỗi
> request tiêu quota từ key Groq / Cerebras / OpenRouter / Gemini của bạn.

Quick tunnel là tạm thời — đóng cửa sổ là URL biến mất, và mỗi lần chạy lại ra
URL mới. Muốn URL cố định thì cần tài khoản Cloudflare cùng một domain, dùng
`cloudflared tunnel create`; khi đó có thể thêm Cloudflare Access để chặn ngay
từ vòng ngoài.

---

## 10. Xử lý sự cố

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| Mọi provider `API key not configured` | `.env` chưa được nạp | Chạy từ thư mục gốc project; kiểm tra file tên đúng `.env` |
| Ollama lỗi kết nối | Sai `OLLAMA_BASE_URL` | Đặt `http://localhost:11434` và kiểm tra `ollama serve` đang chạy |
| Ollama 404 | Thiếu `/v1` | Gateway tự thêm — kiểm tra Ollama có đang chạy không |
| Ollama **402** | Model cloud cần gói trả phí ollama.com | Dùng model khác, hoặc nâng gói |
| Cerebras **402** | Chưa bật billing | Vào tab Billing trên Cerebras |
| Gemini/OpenRouter **404** "no longer available" | Model đã bị gỡ | Đổi model ID, xem mục 8 |
| **429** rate-limited | Hết quota hoặc pool chung đang nghẽn | Đợi, hoặc để fallback lo |
| **503** "All candidate providers failed" | Mọi chặng đều hỏng | Đọc `errors[]` trong response — có lý do từng chặng |
| Nội dung trả về rỗng | Model reasoning dùng hết `max_tokens` cho phần suy nghĩ | Tăng `max_tokens` hoặc bỏ hẳn |
| Tiếng Việt hiện ký tự lạ trên PowerShell | Encoding console | `$env:PYTHONIOENCODING="utf-8"` |
| `stream=true` trả về rác | Đã sửa ở phiên bản hiện tại | Cập nhật `app/main.py` |

---

## 11. Giới hạn đã biết

- Chỉ hỗ trợ `/v1/chat/completions`. Chưa có embeddings, images, audio.
- Không có retry trong cùng một nhà cung cấp — lỗi là chuyển ngay sang nhà kế.
- Không đếm token, không giới hạn tốc độ, không cache.
- Khi streaming, lỗi xảy ra **sau** byte đầu tiên sẽ không fallback được (đúng
  bản chất của SSE).
- Nhà cung cấp miễn phí thay đổi model liên tục. Hãy coi model ID trong
  `.env` là thứ sẽ phải cập nhật định kỳ.
