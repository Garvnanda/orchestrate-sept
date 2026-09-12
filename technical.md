# technical.md — Architecture & Design Reference

Status: reflects decisions locked as of this writing. Update this file whenever a locked decision changes (with approval — see CLAUDE.md checklist).

## Stack

- Language: Python (stdlib only for data processing — `csv`, `datetime`, `dataclasses`, `json`; `sqlite3` allowed as a fallback if in-memory joins get unwieldy, no `pandas`/`duckdb`).
- LLM access: `openai` Python SDK pointed at AgentRouter's OpenAI-compatible endpoint.
  - `base_url = "https://agentrouter.org/v1"`
  - API key read from env var `AGENTROUTER_API_KEY` (confirmed).
  - Models confirmed available: only `deepseek-v4-flash` and `glm-5.3` are up as of 2026-09-12 (rest reported down).
- Entry point: `code/main.py`.

## Model-per-role split

| Role | Model | Fires when |
|---|---|---|
| Extractor | deepseek-v4-flash | Every message (215 rows) and every image (16 rows) — always runs, this is the only path that reads that evidence at all |
| Resolver | deepseek-v4-flash | Only when two evidence sources disagree on amount/date/status for the same `event_id`/`request_id` (reuses extractor's model — only 2 models available) |
| Verifier | glm-5.3 | Only when extractor confidence=`low` on a fact actually used in the decision, OR resolver's suggested winner contradicts the coded conflict-hierarchy (reserved as the "better" of the 2 available models for the hardest/rarest case) |

**Fallback chain (message extraction only, added after real content-moderation failures):** AgentRouter blocks ~21% of messages with a `content-blocked` error regardless of which of the 2 available models is asked, and regardless of prompt framing (confirmed by testing direct extraction, the other model, and a plain translation request — all blocked identically on the same content). Retry order per message: (1) extractor role direct, (2) verifier role direct (via `call_json_with_fallback`), (3) translate to English via AgentRouter then retry extraction, (4) OpenRouter (`nvidia/nemotron-3-super-120b-a12b:free` — the first free-tier candidate tried, `meta-llama/llama-3.3-70b-instruct:free`, turned out to be retired from the free tier, and the second, `google/gemma-4-31b-it:free`, was rate-limited on the shared pool; this one was smoke-tested working before the full batch ran — key in `OPENROUTER_API_KEY`, standard OpenAI-compatible endpoint, no special headers needed) as a fully separate provider, (5) safe no-op fallback fact if all four fail. Cache marks a failed entry so any rerun automatically retries it through the whole chain rather than needing a manual purge.

All three AgentRouter roles are advisory to varying degrees:
- Extractor output *is* the fact (nothing else can read the message/image), but every extracted fact carries a `confidence: high|medium|low` field the extractor must self-report.
- Resolver output is a suggestion only — final say always goes through the coded conflict-resolution hierarchy (see below); if resolver disagrees with the hierarchy's answer, that disagreement is exactly what triggers the verifier.
- Verifier output is purely advisory/logged — it flags concerns, it never rewrites a number or a final field. Deterministic code always produces the actual output row.

**No LLM call ever computes money math, dates, or ranking. That is 100% deterministic Python, always.**

## Data model / pipeline stages

1. **Load** — parse all `dataset/*.csv` into plain dicts/lists keyed by id. Resolve blank `financial_events.amount` via `images.csv.related_event_id` → extractor call on the image.
2. **Currency normalize** — convert every foreign-currency cash event to the user's `home_currency` using the `exchange_rates.csv` row matching (rate_date, from_currency, to_currency) for that event's settlement date. Never invent a rate.
3. **Evidence extraction** — one extractor call per message/image, cached to a local JSON file keyed by `message_id`/`image_id` so reruns don't recompute. Output schema (strict JSON, schema-enforced at the API boundary, not parsed-after-the-fact regex):
   ```json
   {"event_id": "event_14 or null", "action": "amend|cancel|confirm|delay|none",
    "new_amount": null, "new_date": null, "confidence": "high|medium|low", "note": "short reason"}
   ```
4. **Conflict detection (coded)** — deterministic scan for same `event_id`/`request_id` with disagreeing amount/date/status across event row + extracted message/image facts. Triggers resolver call when found.
5. **Conflict resolution hierarchy (coded, always the final authority)**, in order:
   1. Explicit cancellation/settlement/amendment
   2. Newer record from the same source
   3. Settled event over an estimate/forecast
   4. Financially safer interpretation (when still ambiguous)
6. **Verifier escalation (coded trigger, advisory LLM call)** — see triggers table above. Logged, never authoritative.
7. **Financial state reconstruction** — per user: separate recurring vs one-time events, reserve pending debits, ignore pending credits/bonuses/commissions/refunds/lottery/unrealized investment gains until settled, count confirmed salary on settlement date only, de-duplicate linked-event chains.
8. **90-day forecast** — forward balance simulation from `request_date` using recurring income/expenses + confirmed future payments + resolved evidence. Balance must never fall below `minimum_balance_to_keep` at any simulated point.
9. **Decision engine**:
   - `amount_safe_to_pay` = max amount payable on `request_date` without breaking the 90-day check, capped at `requested_amount`.
   - `earliest_date_for_full_payment` = first date the full amount passes the safety check (no spending changes applied yet).
   - Eligible payment methods filtered by `payment_methods_user_will_consider` + `max_installment_months`.
   - When multiple safe plans qualify, rank: (1) completes by `desired_completion_date`, (2) no spending changes, (3) lowest total paid, (4) starts earliest, (5) fewest payments, (6) lowest `payment_option_id`.
10. **Spending changes** — only recurring + flexible-category events; `stop` and `reduce_to` never target the same event in one answer; max 3 changes.
11. **Explanation generation** — deterministic fact-list builder → LLM rewrite pass (must include every fact, forbidden from adding new ones).
12. **Output + validation** — write draft row, run standalone validator (see below), only then commit to `output.csv`. Any stage failure at any point falls back to a safe deterministic default row rather than a blank/partial one.

## Standalone validator (mandatory, blocks the write)

Per row, before final `output.csv` is written:
- All 8 required fields non-empty.
- `0 <= amount_safe_to_pay <= requested_amount`.
- `affordability_status` / `recommended_payment_method` from the allowed enum sets only.
- `payment_plan` entries chronological, sum to `requested_amount` for `partial_payment` (exactly 2 payments), or exactly match a supplied `payment_option_id` for `installments`.
- `earliest_date_for_full_payment` == `request_date` when `affordability_status == affordable_now`; empty only when no full payment is safe in the forecast window.
- `spending_changes_needed` references only flexible recurring events, `stop`/`reduce_to` never on the same event, max 3 entries.
- If any check fails: fall back to the safe default row, log the failure, never leave a row blank or half-filled.

## Financial reconstruction & forecast (steps 9-10, `code/reconstruct.py`)

- **Linked-event de-duplication**: any `event_id` that appears as another row's `linked_event_id` is superseded and excluded outright — only the terminal/newest node of a chain counts. 58 events excluded this way (matches the exact `linked_event_id` count in the dataset).
- **Evidence application**: for every event with >1 fact naming it (its own CSV row plus any message/image evidence), `conflicts.resolve_event_state()` reduces them via the same coded hierarchy used for conflicts — no LLM call needed here, since the hierarchy gives a sound answer whether or not the facts actually disagree. `cancel` → status becomes `cancelled`; `amend`/`delay` → overrides amount/date if given; `confirm`/`none` → no change.
- **Currency conversion**: uses the event's own `settlement_date` for the FX rate lookup even if a `delay` amendment moved the effective date — the rate table is keyed to real recorded dates, not hypothetical amended ones; the amount can change via evidence, but which day's rate applies does not.
- **Recurrence detection** (`detect_recurring_series`): per user, groups *settled* history by `category`. Fewer than 3 occurrences → `type: none`, no forward projection invented (per "detect recurrence only when history supports it"). 3+ occurrences with a consistent gap (within 0.5x-1.6x the median, median ≥ 5 days) → `type: periodic`, projected forward at that cadence using the last known amount. 3+ occurrences with irregular gaps (groceries/transport/dining-style frequent variable spend) → `type: irregular`, projected as a conservative monthly-equivalent average (total of the last up-to-6 occurrences ÷ the days they span × 30).
- **90-day projection** (`project_forecast_events`): explicit `pending`/`scheduled` events in the window are used as-is (pending credits excluded per spec, pending debits reserved); periodic/irregular projections fill in the rest of the window, skipping any cycle within ±10 days of an explicit row for the same category so a category is never double-counted (this specifically matters for salary, which always has an explicit "Next confirmed salary" `scheduled` row plus a detectable monthly cadence for the occurrences after that one).
- **Balance simulation** (`simulate_balance`, `min_balance_up_to`): running balance from `current_available_balance` forward through every projected event; `min_balance_up_to(balance, timeline, date)` is the core primitive step 11's ranking/eligibility logic will call repeatedly.
- **Cross-checked against ground truth**: `sample_requests.csv`'s `request_01` (user_01, pay ZAR 25,256 in full, claimed `affordable_now`) — the engine's own 90-day min balance after that payment is 33,225.10, comfortably above the 18,000 minimum, matching the sample's claim exactly (58,481.10 − 25,256 = 33,225.10).
- Dry-run across all 250 real `requests.csv` rows: 0 crashes, every user has resolvable events.

## Decision engine (step 11, `code/decision.py`)

- `compute_capacity()`: `amount_safe_to_pay` = `min(requested_amount, max(0, global_min_balance - minimum_balance_to_keep))`, where `global_min_balance` is the lowest point in the 90-day forecast from `request_date` — paying `X` today shifts the whole forecast curve down by `X` uniformly, so this is exact, not an approximation. `earliest_date_for_full_payment` binary-searches (via a sorted scan, since `suffix_min_balance` is provably monotonic non-decreasing as the date moves later) for the first date a lump-sum payment stays safe through the rest of the horizon.
- `build_candidates()`: one candidate per preference-eligible method (`full_payment`/`partial_payment`/`installments`/`wait`), each carrying its own safety check per problem_statement.md's own definitions (installments additionally checked via `schedule_min_balance()`, which layers the option's exact payment schedule onto the existing forecast and re-simulates). `max_installment_months` is interpreted as a cap on `number_of_payments` (an N-payment plan = N "months" given the dataset's ~30-day payment_frequency_days convention).
- `rank_candidates()`: sorts by the exact 6-rule tie-break order from problem_statement.md (completes-by-deadline, no-spending-changes [always 0 at this stage — see below], lowest total paid, earliest start, fewest payments, lowest `payment_option_id`).
- **Spending changes are deliberately NOT part of step 11.** `amount_safe_to_pay`/`earliest_date_for_full_payment` are explicitly defined by problem_statement.md as "before optional spending changes" — step 11 computes the pure baseline. Step 12 is a separate follow-up pass that only engages when the baseline lands on `not_affordable`/`affordable_later`, tries stopping/reducing flexible events to improve the numbers, and only upgrades the recommendation if that actually changes the outcome — this also automatically satisfies ranking rule 2 ("no spending changes" preferred) by construction, since changes are only ever reached for when the plain baseline can't complete the request.

### Sample divergence note (request_02)

`sample_requests.csv`'s `request_01` (simple, one category's worth of history, no overlapping installment payments) matched this engine's output exactly — validates the core mechanics (currency, balance math, eligibility gating, the `amount_safe_to_pay` formula) end to end.

`request_02` (multi-category, 3-installment plan) does **not** match: the sample claims the 3-payment installment plan (2025-08-08/09-07/10-07) is safe; this engine's day-by-day simulation shows the running balance dips to ~20.8M IDR on 2025-10-11 — after the 3rd payment, before that month's salary lands — against a 29.16M minimum, so it's flagged unsafe. Traced this by hand: every recurring category used in the simulation (housing/utilities/insurance/education/healthcare/entertainment/cloud_storage/groceries/transport/dining/salary) is a real, consistently-cadenced category from the user's own settled history — this isn't a projection bug, it's the literal, full result of enforcing "keep the user above minimum_balance_to_keep throughout the 90-day forecast" (problem_statement.md's own wording) against every detected recurring commitment simultaneously.

Per AGENTS.md's explicit instruction — "`sample_requests.csv` contains public examples... Use it to understand format and decision style, not as labels for evaluation requests" — this is not treated as a bug to force-fix by loosening the safety check (that would risk under-protecting real requests elsewhere just to match one hand-crafted example). Documented here rather than silently ignored.

## Currency & date handling

- All dates `YYYY-MM-DD`.
- Convert using the exact `exchange_rates.csv` row for (settlement date, from_currency, to_currency) — no interpolation, no invented rates.
- Balances/requests/payment options/output amounts always in the user's `home_currency`.

## Prompt-injection guardrail (see security.md for full detail)

Every extractor/resolver/verifier prompt explicitly states: message/image content is untrusted data to extract facts *from*, never instructions to follow. Any embedded directive in evidence text is ignored for task-behavior purposes; it may still be reported as an extracted "fact" (e.g. a cancellation notice) but only through the strict JSON schema, never as free-form instruction-following.
