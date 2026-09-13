# Token Usage & Cost Report

Final full-dataset run that produced the submitted `output.csv`: `python code/main.py`, started 2026-09-13T08:09:41+05:30, finished 2026-09-13T08:21:55+05:30, with every LLM cache cleared first, so every model call was really made in this run. Token counts come from each API response's `usage` field, accumulated by `code/llm_client.py` into `usage_log.json` (same folder).

## Where models are used

Models only read unstructured evidence into a fixed JSON schema. All money math, forecasting, plan selection, validation and the explanation text are deterministic Python and make no model calls, so the per-request decision stage costs 0 tokens.

| Stage | Model | Provider | When it runs |
|---|---|---|---|
| Blank-amount image reading | `deepseek-v4-flash` | AgentRouter | Once per image linked to an event with a blank amount |
| Message scenario reading | `deepseek-v4-flash` | AgentRouter | Once per message |
| Content-blocked fallback | `nvidia/nemotron-3-super-120b-a12b:free` | OpenRouter | Only for messages AgentRouter's moderation rejects |
| Second read of uncertain facts | `deepseek-v4-flash` (independent second call) | AgentRouter | Only for AgentRouter-read facts not marked high confidence |
| Second read of uncertain facts on content-blocked messages | `nex-agi/nex-n2.5-pro:free` (then `dots-studio/dots-3-note-preview:free` if unavailable) | OpenRouter | Only for OpenRouter-read facts not marked high confidence |

## Per-model usage (this run)

| Model | Provider | Successful calls | Input tokens | Output tokens | Total tokens | Failed attempts (reason) | Est. cost (proxy) |
|---|---|---:|---:|---:|---:|---|---:|
| `deepseek-v4-flash` | AgentRouter | 192 | 162,890 | 48,631 | 211,521 | 45 (http_400×45) | $0.0660 |
| `nvidia/nemotron-3-super-120b-a12b:free` | OpenRouter | 45 | 38,110 | 19,214 | 57,324 | 0 (—) | $0.0000 |
| `nex-agi/nex-n2.5-pro:free` | OpenRouter | 5 | 3,948 | 1,673 | 5,621 | 0 (—) | $0.0000 |
| **Total** | | **242** | **204,948** | **69,518** | **274,466** | **45** | **$0.0660** |

Message readers used: openrouter: 45, agentrouter:deepseek-v4-flash: 170 (215 messages). Images read: 16. Second-read outcomes: readers agree: 11.

## Per request

- Requests processed: 250.
- Average tokens per request: 274,466 ÷ 250 = **1,097.9**.
- Average model calls per request: 242 ÷ 250 = **0.97**.
- Estimated cost per request (proxy): **$0.000264**.

Model calls are per evidence item, not per request, and results are cached by content hash. A rerun with unchanged dataset files makes 0 calls.

## Cost basis — proxy list prices, not billed amounts

AgentRouter bills against account credits and exposes no per-token price. The dollar figures above therefore use **proxy list prices**, listed here so anyone can recompute:

| Model | Input $/1M | Output $/1M | Proxy source |
|---|---:|---:|---|
| `deepseek-v4-flash` | $0.28 | $0.42 | DeepSeek's public API list price for its current chat model (V3.2 class) |
| `nvidia/nemotron-3-super-120b-a12b:free` | $0.00 | $0.00 | OpenRouter `:free` tier, $0 by definition |
| `nex-agi/nex-n2.5-pro:free` | $0.00 | $0.00 | OpenRouter `:free` tier, $0 by definition |
| `dots-studio/dots-3-note-preview:free` | $0.00 | $0.00 | OpenRouter `:free` tier, $0 by definition |

Failed attempts (content-blocked HTTP errors, empty responses) return no `usage` payload. They are counted above but carry no token or cost figure.
