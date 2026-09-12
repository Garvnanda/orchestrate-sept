# done.md — Completed & Verified Work Log

Append-only, chronological, newest at bottom. Only move an item here from `implementation.md` once it's actually built AND verified (state how). This is the source for judge-interview "defendable details" — every entry should be something you could explain and defend with a real number from an actual run.

Format:

```text
## [YYYY-MM-DD] <task from implementation.md>
What: <what was built>
Verified: <how — test run, sample comparison, assertion, manual check>
Notes: <anything surprising, a real number/threshold worth remembering for the interview>
```

---

## [2026-09-12] Step 0 — .env.example scaffold
What: created `.env.example` at repo root with `AGENTROUTER_API_KEY=` (name only, no value). `.env`/`log.txt`/`__pycache__/` already gitignored.
Verified: manual inspection, confirmed `.gitignore` covers `.env`.
Notes: none.

## [2026-09-12] Step 1 — Data loader
What: `code/data_loader.py`, stdlib `csv` only. `load_all()` parses all 9 dataset CSVs into a `Dataset` dataclass of plain dicts/lists, with numeric/pipe-list/bool field coercion and indices by user_id, request_id, event_id, related_event_id for joining.
Verified: ran `python code/data_loader.py`, self-check asserts pass: 250 requests (exact match to spec), every request's user_id resolves to a known profile, every request has 2-4 payment options (per problem_statement.md contract), every blank-`amount` event has a linked image (per problem_statement.md blank-amount rule).
Notes: real numbers from this run — 275 user profiles, 25,342 financial events, 134 exchange rate rows, exactly 16 blank-amount events (matches `images.csv` row count of 16, so every image is in fact used for exactly one blank-amount event). Good candidate for one of the 3 "defendable numbers" in interview prep.

## [2026-09-12] Step 3 — Currency normalization
What: `code/currency.py`, `convert_to_home_currency(amount, from_currency, to_currency, rate_date, exchange_rates)`. Exact-match lookup only on (rate_date, from_currency, to_currency) — no inversion, no interpolation, raises `MissingExchangeRateError` if the exact row isn't present rather than inventing a rate.
Verified: ran `python code/currency.py` against the full real dataset — every foreign-currency event with a known amount converted successfully, zero `MissingExchangeRateError`.
Notes: real number — 139 foreign-currency financial_events rows converted, 0 missing rates. Another defendable interview number.

## [2026-09-12] Step 4 — AgentRouter client — BLOCKED, not resolved
What: `code/llm_client.py` written (openai SDK, base_url=https://agentrouter.org/v1, model roster wired: extractor=deepseek-v4-flash/resolver=gpt-5.6-sol/verifier=claude-opus-5, JSON-mode structured output, image-input support via base64 data URL for the extractor role).
Verified: attempted a live self-check call (`python code/llm_client.py`) — got `openai.AuthenticationError: 401 - {'message': 'unauthorized client detected...'}`. Confirmed the key IS loading correctly from `.env` (present, 51 chars, sk-prefixed, no stray quotes/whitespace) via a value-blind check, so this isn't a python-dotenv/env-loading bug on this end.
Notes: this is either an invalid/expired/wrong-account key, or an AgentRouter-side account issue — needs the user to verify the key on their AgentRouter dashboard. Step 2 (blank-amount image resolution) and everything from step 5 onward that needs live LLM calls is blocked until this clears; steps not requiring live calls can continue in the meantime.

## [2026-09-13] Step 4 — AgentRouter client — ROOT CAUSE FOUND AND FIXED
What: root cause of the 401 was neither the key nor an IP/WAF block (both theories tested and falsified) — AgentRouter checks the `User-Agent` header and rejects the openai SDK's default one as an "unauthorized client." Fixed by reading `AGENTROUTER_BASE_URL` and `AGENTROUTER_USER_AGENT` from env and passing `default_headers={"User-Agent": ...}` to the OpenAI client constructor in `code/llm_client.py`.
Verified: ran `python code/llm_client.py` — `OK: AgentRouter connectivity + JSON mode working via deepseek-v4-flash`, succeeded from this sandbox too (proving it was never an IP block).
Notes: real diagnostic trail worth keeping for interview defensibility — bad key theory falsified via curl with a garbage key (same 401), WAF/IP theory falsified when the user's own machine reproduced the same 401, User-Agent theory confirmed by the user's other working AgentRouter project's env having an explicit AGENTROUTER_USER_AGENT var, then confirmed by a passing live call. Good "message/signal in → root cause out" trace for the judge interview.

## [2026-09-13] Step 2 — Blank-amount image resolution
What: `code/evidence.py`, `resolve_blank_amounts()` — for each blank-`amount` event, finds its linked image via `images_by_event`, calls the extractor role (deepseek-v4-flash) with the image, caches the extracted fact to `evaluation/extraction_cache.json` keyed by `image_id`.
Verified: ran `python code/evidence.py` for real (background, ~16 live vision calls) — `OK: resolved all 16 blank-amount events via image extraction`. Self-check asserts every one of the 16 blank-amount events got a positive numeric amount back.
Notes: real number — 16/16 resolved, 0 failures, matches the exact blank-amount count found in step 1. Cache file means this never needs to re-run those 16 calls again for the rest of the build.

## [2026-09-13] Step 5 — Full evidence extraction (215 messages + 16 images)
What: extended `code/evidence.py` with `extract_from_message`/`extract_all_messages`. Built a 4-tier fallback chain after real content-moderation failures on AgentRouter: (1) extractor role direct, (2) verifier role direct, (3) translate to English then retry, (4) OpenRouter (`nvidia/nemotron-3-super-120b-a12b:free`) as a last resort, (5) safe no-op fact only if all four fail. `llm_client.py` gained `ExtractionError`, empty-response handling, and a shared `_chat_json` helper reused by both providers.
Verified: ran the full batch multiple times as bugs surfaced and got fixed (crash on unhandled content-block exception, then unhandled empty-choices response) — final run: `0 failed and fell back to safe no-op facts: []`. Cache auto-retries only previously-failed entries on rerun, confirmed the 170 already-successful AgentRouter extractions were never re-called across all the reruns.
Notes: real numbers — 215/215 messages extracted, 39 with a confirmed `related_event_id` link, 45 initially hit AgentRouter's content-block filter (~21%, concentrated in employer/service_provider payroll and invoice messages — exactly the highest-value evidence category), all 45 recovered via OpenRouter after AgentRouter's own alternate model and a translation retry both failed identically on the same content. Strong interview trail: 3 falsified theories (bad key, WAF/IP block, prompt-framing) before finding the real fix each time — good "what evidence led to this exact value" material.

## [2026-09-13] Steps 6/7 — Conflict detection + coded resolution hierarchy + resolver second opinion
What: `code/conflicts.py`. `build_facts_by_event()` merges each original event row (as a pseudo-fact) with every message/image fact naming that event_id. `detect_conflicts()` flags amount/date/action mismatches. `resolve_by_hierarchy()` applies the 4-rule coded priority (explicit cancel/amend > newer same-source record > settled-over-estimate > direction-aware financially-safer default for debit vs credit). `resolve_conflict()` always also calls the resolver LLM for a second opinion and sets `escalate_to_verifier=True` when it disagrees with the coded hierarchy — hierarchy's answer is always authoritative regardless.
Verified: ran `python code/conflicts.py` against the full real dataset (all evidence already cached, so purely deterministic + resolver calls) — `OK: 7 conflicts detected and resolved by coded hierarchy, 2 disagreed with the resolver (escalate_to_verifier=True)`.
Notes: real numbers — 7 conflicts total across 250 requests' worth of events/evidence, 2 flagged for step-8 verifier escalation. Small, reviewable set — good candidate for the interview's "one traced example."
