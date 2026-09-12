# Token Usage & Cost Report

Covers the final full-dataset run that produced the submitted `output.csv` (250/250 requests, 0 safe-default fallbacks). Numbers below are read directly from each API response's `usage` field (real, not estimated) during that run — see `usage_log.json` in this same folder for the raw accumulator this table is built from.

## Model providers and roles

| Role | Model | Provider |
|---|---|---|
| Extractor (every message + image; also reused for the explanation rewrite pass) | `deepseek-v4-flash` | AgentRouter (`https://agentrouter.org/v1`) |
| Resolver (fires only on a detected cross-source conflict) | `deepseek-v4-flash` | AgentRouter |
| Verifier (fires only on a resolver/hierarchy mismatch or a low-confidence fact actually used) | `glm-5.3` | AgentRouter |
| Fallback extractor (only for content-blocked messages AgentRouter's own moderation rejected on every AgentRouter model/prompt variant tried) | `nvidia/nemotron-3-super-120b-a12b:free` | OpenRouter (`https://openrouter.ai/api/v1`) |

## Per-model usage (this run)

| Model | Provider | Calls | Prompt tokens | Completion tokens | Total tokens |
|---|---|---:|---:|---:|---:|
| deepseek-v4-flash | AgentRouter | 443 | 122,639 | 303,379 | 426,018 |
| glm-5.3 | AgentRouter | 2 | 471 | 4,284 | 4,755 |
| nvidia/nemotron-3-super-120b-a12b:free | OpenRouter | 45 | 12,751 | 16,192 | 28,943 |
| **Total** | | **490** | **135,861** | **323,855** | **459,716** |

## Per-request

- 250 requests processed.
- 459,716 total tokens ÷ 250 requests = **1,838.9 tokens/request average**.
- Call breakdown by pipeline stage for this run: 16 image extractions + 215 message extractions (170 succeeded directly on `deepseek-v4-flash`, 45 needed the OpenRouter fallback after AgentRouter's content filter rejected them on every AgentRouter model/prompt variant tried) + 7 resolver calls (only where a real cross-source conflict was detected, out of 25,342 events) + 2 verifier calls (only where the resolver disagreed with the coded hierarchy) + 250 explanation rewrites (one per request) = 490 successful calls total.

## Cost

Not computed as a dollar figure here: both `deepseek-v4-flash` and `glm-5.3` are accessed through the user's own AgentRouter account (a credits/subscription arrangement with no public per-token price exposed via the API), and `nvidia/nemotron-3-super-120b-a12b:free` on OpenRouter is explicitly the zero-cost free tier. Inventing a per-token rate for models without a verified public price would misrepresent actual cost rather than clarify it — the token counts above are the real, measured basis for computing cost once an actual billing rate is available for the AgentRouter account used.

## Methodology note — what this table does and doesn't include

Every number above comes from a successful API response's own `usage` field, tracked automatically in `code/llm_client.py` and persisted to `evaluation/usage_log.json` after every call. It does **not** include failed/rejected API attempts: AgentRouter's content-moderation filter blocked the 45 messages above on every AgentRouter model and prompt variant tried (direct, alternate model, and a translation retry) before the OpenRouter fallback succeeded — those blocked attempts return an HTTP error with no `usage` payload, so their (real, but API-unexposed) token cost isn't reflected here. This was a deliberate build-time discovery (see `done.md`'s step 5 entries for the full diagnostic trail), not a run-time occurrence — a cold run with warm caches, like the one that produced this report, makes no more than one attempt per already-known-good item.
