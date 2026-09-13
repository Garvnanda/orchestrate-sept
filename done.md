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

## [2026-09-13] Fix — resolver/verifier caching (determinism bug caught before it mattered)
What: `resolve_conflict()` and `run_verifier_escalations()` had no cache, unlike the extractor — every rerun re-queried the LLM fresh. Caught this because rerunning `resolve_all_conflicts()` produced 1 escalation instead of the earlier run's 2, for identical input data — a real violation of "keep behavior deterministic where possible." Added `evaluation/resolution_cache.json`, same pattern as the extraction cache.
Verified: ran `conflicts.py` twice in a row after the fix — identical result both times (7 conflicts, 1 escalation), confirmed deterministic.
Notes: the earlier "2 escalations" number in the step-6/7 entry above is superseded by this fix; the correct, now-stable number is 1. Worth mentioning in interview: caught and fixed a determinism bug via a straightforward before/after rerun comparison.

## [2026-09-13] Step 8 — Verifier escalation (advisory only)
What: `conflicts.run_verifier_escalations()` — reviews every resolver/hierarchy mismatch (`escalate_to_verifier=True`) and every low-confidence fact that was actually used in an event's resolved state, via the `glm-5.3` verifier role. Purely advisory: writes a `looks_sound`/`reasoning` opinion, never changes any resolved fact.
Verified: ran for real against the full dataset — 0 low-confidence-used escalations (all 231 extracted facts that mattered had `confidence != low`), 1 resolver-mismatch escalation. Saved to `evaluation/verifier_log.json`. The verifier's opinion (`looks_sound: false`, flagging that the resolver's own stated reasoning was internally inconsistent) is logged but does not override the coded hierarchy's answer — exactly per design.
Notes: real number — 1 verifier review total for the whole dataset, cheap and reviewable. Good interview material for "here's a case the system flagged as uncertain and why it still made a safe call anyway."

## [2026-09-13] Steps 9/10 — Financial state reconstruction + 90-day forecast engine
What: `code/reconstruct.py`. `build_resolved_events()` merges blank-amount resolution, evidence-based amendments/cancellations (coded hierarchy, no LLM), currency conversion, and linked-chain de-duplication into one resolved view per event. `detect_recurring_series()` classifies each user's settled history per category as periodic/irregular/insufficient. `project_forecast_events()` builds the 90-day window's cash-flow events (explicit + projected, never double-counted). `simulate_balance()`/`min_balance_up_to()` give the running balance and the query primitive step 11 needs.
Verified: `python code/reconstruct.py` — 25,284 resolved events (58 superseded by linked chains, exactly matching the dataset's `linked_event_id` count), and a hard cross-check against `sample_requests.csv`'s `request_01`: after paying the full ZAR 25,256, min balance over 90 days computed as 33,225.10, correctly ≥ the 18,000 minimum, exactly matching 58,481.10 − 25,256 by hand. Also dry-ran the full pipeline (`build_all` + `detect_recurring_series` + `project_forecast_events` + `simulate_balance`) against all 250 real `requests.csv` rows — 0 crashes, every user resolved.
Notes: real numbers — 25,284 resolved events, 58 deduped, 1 sample cross-check passed exactly, 250/250 real requests processed without error. Strong "one traced example" candidate for the interview (request_01, user_01, full trace from raw event rows to a validated 90-day-safe balance).

## [2026-09-13] Fix — recurring-detection threshold caused an artificial deficit (caught by the request_01 cross-check)
What: original `detect_recurring_series` required 3+ *settled* occurrences to project a category forward. A brand-new employee (user_01: 1 settled "Prorated first salary" + 1 scheduled "Next confirmed salary") never cleared that bar, so salary got projected zero times beyond the single explicit scheduled row, while every expense category (5-6 months of settled history) got projected fully for all 90 days — a real asymmetry that manufactured a ~33K ZAR artificial deficit and flipped `affordable_now` into `not_affordable`.
Verified: lowered the bar to 2 occurrences when one is an explicitly `scheduled` (confirmed) instance, with a plausible-cadence check (5-45 days) replacing the multi-gap consistency check that needs 3+ points. Reran — request_01 now matches `sample_requests.csv` exactly (`amount_safe_to_pay=25256`, `affordable_now`, `full_payment`, plan `2024-03-03:25256`, `earliest_date_for_full_payment=2024-03-03`).
Notes: caught via the ground-truth cross-check, not by inspection — another point for "verification catches real bugs" in the interview.

## [2026-09-13] Step 11 — Decision engine
What: `code/decision.py`. `compute_capacity()` derives `amount_safe_to_pay`/`earliest_date_for_full_payment` from the 90-day forecast (exact, not approximated — a same-day payment shifts the whole curve by that amount). `build_candidates()` generates one safety-checked candidate per preference-eligible method. `rank_candidates()` applies the exact 6-rule tie-break order from problem_statement.md. `decide()` picks the winner and derives `affordability_status` from which method won.
Verified: request_01 (sample_requests.csv) matches exactly after the recurrence-threshold fix above. request_02 diverges from the sample on a complex multi-category/multi-installment case — traced by hand, confirmed not a bug (every recurring category is real, consistently-cadenced history), documented in technical.md as a modeling-assumption difference on a sample AGENTS.md explicitly says isn't a scoring label. Dry-ran all 250 real requests: 0 crashes, every `amount_safe_to_pay` within `[0, requested_amount]`, healthy status spread (not_affordable 83, affordable_now 64, affordable_with_plan 54, affordable_later 49 — not degenerate into one bucket).
Notes: real numbers — 250/250 requests processed, 1 exact ground-truth match, distribution looks plausible pre-spending-changes (step 12 will move some of the 83+49 into affordable_with_plan where a flexible cut unlocks it).

## [2026-09-13] Step 12 — Spending-changes generator
What: `code/spending_changes.py`. Only engages when the step-11 baseline is `wait`/`not_recommended` (an already-successful baseline satisfies "no spending changes preferred" by construction). `find_flexible_reductions()` finds recurring categories the user is actually willing to stop/reduce (per `financial_profiles.csv`, never a protected category), ranked by cash recovered; `stop` and `reduce_to` are deduped to one action per category (mutual exclusivity). `try_with_spending_changes()` tries 1, then 2, then 3 changes (fewest first) and checks whether that unlocks a safe `full_payment` today or a safe installment option — `amount_safe_to_pay`/`earliest_date_for_full_payment` are never altered, only the recommendation/plan, per their explicit "before optional spending changes" definitions.
Verified: ran across all 250 real requests — 13 upgraded from `not_affordable`/`affordable_later` to `affordable_now`/`affordable_with_plan` via spending changes, 237 unchanged (already fine, or genuinely not rescuable by trimming discretionary categories alone). All upgrades respect the 3-change cap.
Notes: real number — 13/250 (5.2%) needed spending changes to become affordable. Good defendable number for the interview ("here's exactly how many of the real 250 requests needed this mechanism, and why").

## [2026-09-13] Fix — spending-changes-unlocked full payment mislabeled affordable_now (caught by the validator, not silently)
What: `spending_changes.py`'s full-payment-via-changes branch labeled the result `affordable_now`. But `affordable_now` requires `earliest_date_for_full_payment == request_date` with no changes (that field is explicitly baseline/pre-change per its own spec definition) — a spending-changes-assisted outcome is `affordable_with_plan` by definition ("...using a partial-payment schedule, installments, or permitted spending changes"). The mismatch was caught by `validate.py`'s own contract check on the first real full run, which correctly refused the invalid row and fell back to the safe default for `request_99`/`request_117` rather than writing something wrong.
Verified: changed the status to `affordable_with_plan`, reran those 2 requests directly — both now validate cleanly (e.g. `request_99`: `affordable_with_plan`/`full_payment`/`2026-07-04:18062` with `reduce_to:event_9232:1065.90`).
Notes: exactly the scenario the standalone validator + safe-default-fallback pair was built for — a real bug caused 2/250 rows to nearly ship wrong, and the safety net caught it (2 safe-default rows instead of 2 wrong ones) while the actual root cause got found and fixed on the same run. Strong interview example of the validator earning its keep.

## [2026-09-13] Steps 16/17 — Full run verified
What: after the affordable_now/affordable_with_plan fix above, did a full clean cache-clear-and-rerun of the entire pipeline (extraction, resolver/verifier audit, main.py) so every number is freshly, consistently tracked from one canonical run.
Verified: `python code/main.py` — `wrote 250 rows to output.csv, 0 used the safe-default fallback`. Confirmed structure: 251 lines (250 + header), exact required column order, status distribution not_affordable=73/affordable_with_plan=67/affordable_now=64/affordable_later=46 (method distribution consistent: full_payment=68 = 64 pure-baseline + 4 spending-changes-unlocked, matching the affordable_with_plan fix exactly).
Notes: real numbers — 0/250 fallbacks on the canonical run (down from 2/250 pre-fix). 46+67=113 requests use a plan or wait; 73 genuinely can't be made safe within the 90-day forecast even with permitted changes.

## [2026-09-13] Step 18 — usage_report.md
What: instrumented `code/llm_client.py` to record real per-call `prompt_tokens`/`completion_tokens` from every successful API response (`_record_usage`, persisted incrementally like the other caches). Did a full cache-clear-and-rerun (extraction 231 calls, resolver/verifier audit 8 calls, main.py 250 explanation calls) so every number is freshly measured from one clean run rather than assembled from caches accumulated across many earlier debugging turns. Consolidated all runtime caches from a stray root-level `evaluation/` into `code/evaluation/` (alongside the pre-existing `usage_report.md`/now-removed empty `main.py` stub from the starter template) so `code.zip` is self-contained.
Verified: 490 total successful calls, 459,716 total tokens (135,861 prompt + 323,855 completion) across deepseek-v4-flash (443 calls, AgentRouter), glm-5.3 (2 calls, AgentRouter), nvidia/nemotron-3-super-120b-a12b:free (45 calls, OpenRouter). Cross-checked the 443 figure by hand: 170 clean message extractions + 16 image extractions + 7 resolver calls + 250 explanation rewrites = 443, exact match — confirms the tracking is internally consistent, not just plausible-looking.
Notes: cost intentionally left uncomputed as a dollar figure — AgentRouter's `deepseek-v4-flash`/`glm-5.3` are billed via the user's own account with no public per-token rate exposed via the API, and the OpenRouter model used is explicitly free-tier; inventing a price would misrepresent cost rather than clarify it. Also documented (transparently, in usage_report.md) that ~45 messages' worth of blocked/retried attempts before the OpenRouter fallback succeeded aren't reflected in the token counts, since a failed API call's error response carries no `usage` field — a real, structural gap in what's measurable, not something glossed over.

## [2026-09-13] Step 20 — Judge-interview prep

**One fully-traced example: `request_01` (user_01).** Input: "Would paying for the laptop today leave enough for my regular expenses? ... ZAR 25,256", `request_date=2024-03-03`, `desired_completion_date=2024-03-20`, `allows_partial_payment=true`.
1. `data_loader` — user_01's profile: ZAR, `current_available_balance=58,481.10`, `minimum_balance_to_keep=18,000`, `full_payment` in accepted methods.
2. `evidence`/`currency` — no blank amounts or foreign currency for this user; no message/image evidence names either of their salary events, so both stay as originally recorded.
3. `reconstruct.detect_recurring_series` — rent/utilities/education/debt_repayment/music_subscription/delivery_membership/groceries/transport/dining classified periodic from 5-6 months of settled history. Salary classified periodic too (this is the exact case the recurrence-threshold bugfix above targets: 1 settled "Prorated first salary" + 1 scheduled "Next confirmed salary" = 2 points, one an explicit confirmed anchor) at 23,320/month.
4. `project_forecast_events` builds the 90-day window (2024-03-03 → 2024-06-01): explicit scheduled salary (Mar 15, +23,320), explicit pending transport (Mar 5, -567.60), plus every detected category's projected occurrences.
5. `decision.compute_capacity` — global min balance across that window, minus `minimum_balance_to_keep`, capped at `requested_amount` = exactly 25,256 → `amount_safe_to_pay=25,256`, `earliest_date_for_full_payment=2024-03-03` (today).
6. `build_candidates`/`rank_candidates` — `full_payment` is accepted and safe today → the only real candidate, wins outright. `spending_changes.py` never engages (baseline already succeeded, satisfying "no changes preferred" by construction).
7. `explanation.generate_explanation` — fact list (requested/safe amounts, status, method, plan, min-balance, no changes) → LLM rewrite (`deepseek-v4-flash`), numeric-completeness guard passed.
8. `validate.validate_row` — `affordable_now` requires `earliest_date_for_full_payment == request_date` ✓, bounds ✓, enums ✓ → row accepted.
9. **Cross-check**: `sample_requests.csv`'s own answer for `request_01` matches this engine's output exactly on every field.

**3 defendable numbers, each traceable to a specific file:**
1. **45/215 (20.9%)** messages hit AgentRouter's own content-moderation filter on completely benign financial text (Bahasa Indonesia payroll/invoice notices) — recovered 100% via a 4-tier fallback chain ending in OpenRouter. Evidence: `code/evaluation/extraction_cache.json` note fields; full diagnostic trail (3 falsified theories before the real fix) in this file's step-5 entries.
2. **58** events excluded from cash-flow reconstruction via `linked_event_id` chain de-duplication — exactly matches the dataset's own count of populated `linked_event_id` rows (independently verified by direct CSV inspection, not approximated).
3. **13/250 (5.2%)** real requests needed the spending-changes mechanism to become affordable at all; **73/250 (29.2%)** remain `not_affordable` even after that mechanism is tried — proof the mechanism is genuinely exercised, not dead code, and that the system doesn't force affordability where the numbers don't support it.

**One monitoring signal: the validator's safe-default-fallback rate** (rows where the pipeline had to give up and ship the safest possible default instead of a real evidence-based answer). Currently **0/250 (0%)** on the final canonical run — but was **2/250** earlier the same day, and that non-zero reading is exactly what led straight to finding and fixing the `affordable_now`-vs-`affordable_with_plan` mislabeling bug above. Action if this drifts above 0% in production: treat it as a P0, not a soft warning — pull the specific `request_id`'s `decision_explanation` (it names the exact validation failure) and root-cause immediately, the same way it worked this time.

---

# Post-audit rework (2026-09-13). The entries above describe the deleted design; where they conflict with the entries below, the entries below are correct.

## [2026-09-13] Audit findings that triggered the rework
What: a judge-style audit of the old pipeline against `sample_requests.csv` found 3/25 samples fully exact (status 13/25, earliest date 8/25), 2 invalid `full_payment` rows the old validator accepted, a dataset path that only worked from the repo root, and `image_09`'s blank amount never read. The user chose a full rework.
Verified: re-scoring with `code/evaluate_samples.py` before and after (table in technical.md).

## [2026-09-13] R1-R11 — rebuilt pipeline
What: `scenarios.py` (scenario vocabulary, schema normalization, hash-keyed caches, second read only on non-high-confidence facts), `forecast.py`, `balance.py` (suffix-min semantics; a local variable named `balance` shadowed the module and was renamed `current`), `decision.py` (deadline gate on every candidate), `spending_changes.py` (rewritten after the 2 invalid rows), deterministic `explanation.py` templates, strict `validate.py`, `evaluate_samples.py`, `main.py` loud failure. `evidence.py`, `conflicts.py`, `reconstruct.py` deleted.
Verified: sample scores status 20/25, method 20/25, plan 20/25, earliest 17/25, changes 20/25, explanation wording 14/25, amount exact 3/25, all fields exact 3/25. `image_09` amount now resolved. In-sample calibration, so optimistic.

## [2026-09-13] R12 — clean tracked run + usage_report.md
What: cleared every model cache, ran `python code/main.py` from 07:06:51 to 07:19:00 IST, then generated `code/evaluation/usage_report.md` from `usage_log.json`, `escalation_log.json` and the caches.
Verified: `OK: wrote 250 rows ..., 0 used the safe-default fallback`; 251 lines, exact header. Status affordable_with_plan 80 / not_affordable 64 / affordable_now 54 / affordable_later 52; method full 64 / not_recommended 64 / installments 59 / wait 52 / partial 11; 31 rows with spending changes. Identical distributions to the prior warm-cache run. Sample eval unchanged. Usage: 233 successful calls (deepseek-v4-flash 186, glm-5.3 2, nemotron free 45), 262,827 tokens (197,504 in / 65,323 out), 1,051 tokens and 0.93 calls per request, 98 failed attempts (all http_400 content blocks), proxy cost $0.0701 total / $0.000281 per request. This replaces the step-18 numbers above (490 calls came from 250 explanation rewrites that no longer exist).
Notes: 8 of 10 second reads were unavailable because `glm-5.3` is content-blocked on the same Indonesian messages; the first read was kept for those (documented behaviour, flagged to the user).

## [2026-09-13] R13 — chat_transcript.md
What: verbatim export of the session JSONL: 45 user prompts, 125 assistant texts, 431 tool calls, 430 results; tool payloads over 2,500 chars truncated with a marker; thinking and system reminders omitted; `.env` key values, `sk-` keys, bearer tokens and emails redacted.
Verified: exporter refuses to write if any `.env` key value remains; 845,759 chars written. `log.txt` kept as the alternative; the user picks.

## [2026-09-13] Interview prep (replaces step 20 above)
**Trace, request_01:** `data_loader` loads user_01 (ZAR, balance 58,481.10, minimum 18,000). `scenarios` has no messages or blank amounts for this user, so 0 model calls. `forecast.build_forecast` projects 90 days: payroll stream on its mode pay day, recurring rent/utilities/groceries etc. at their median from the latest settled event, the pending transport debit reserved. `balance.suffix_min_balance` on 2024-03-03 minus 18,000 is above 25,256, so `amount_safe_to_pay=25,256`. `decision` keeps `full_payment` (accepted, meets deadline, cheapest, earliest, one payment). `spending_changes` does not run. `explanation` fills the affordable-now template. `validate` passes. Matches the sample on the decision fields.
**3 numbers:** (1) 45/215 messages are content-blocked by AgentRouter and read by OpenRouter's free model; (2) 20/25 sample status matches after the rework, up from 13/25, with 3/25 exact on every field because the organizer's variable-spend estimator is not recoverable; (3) 262,827 tokens / 233 calls for 250 requests, about $0.07 at proxy prices, and 0 calls on a rerun.
**Plain definitions:** suffix minimum = lowest balance from a date to the end of the forecast, i.e. what a payment on that date would face. Financially safer reading = when two readers disagree, drop the fact that would raise income.
**Monitoring signal:** safe-default fallback count (0/250). Second signal: escalation outcomes in `escalation_log.json`.

## [2026-09-13] R14 — code.zip + fresh-unzip test
What: rebuilt `code.zip` (28 files, 78,073 bytes: top-level docs, README, requirements, `.env.example`, `code/` incl. `evaluation/` caches and `usage_report.md`).
Verified: builder asserts no `.env`, `log.txt`, `chat_transcript.md`, `dataset/`, `__pycache__`, and no `.env` key value in any file. Unzipped into a scratch folder, copied `dataset/` in, ran `code/main.py` from a different working directory with both API key variables unset: 250 rows, 0 fallbacks, `output.csv` sha256 identical to the repo's, `usage_log.json` unchanged (0 model calls).

## [2026-09-13] glm-5.3 removed — deepseek-v4-flash is the only AgentRouter model (supersedes R12 usage numbers)
What: on the user's instruction, removed `glm-5.3` from `llm_client.MODELS` and every call in `scenarios.py`. Message reading: `deepseek-v4-flash` → OpenRouter (content blocks only). Blank amounts: `deepseek-v4-flash`. Second read: a repeat `deepseek-v4-flash` call for AgentRouter-read messages; messages first read by OpenRouter get no second read (AgentRouter already rejected them). Cleared all caches and re-ran from 07:28:38 to 07:41:16 IST, regenerated `usage_report.md`, rebuilt `code.zip`.
Verified: 250 rows, 0 fallbacks; `output.csv` byte-identical to the run before the change; sample eval unchanged. Usage: 237 successful calls (deepseek-v4-flash 192, nemotron free 45), 275,502 tokens (200,989 in / 74,513 out), 1,102 tokens and 0.95 calls per request, 45 failed attempts (http_400 content blocks), proxy cost $0.0690 / $0.000276 per request. Second reads: 6 agree, 6 unavailable (OpenRouter-read). Zip 28 files, secret/forbidden-file checks pass; fresh unzip with keys unset reproduces `output.csv` and makes 0 calls. No `glm` string left in code or the usage report.
Notes: the escalated message set differs from the previous run (12 vs 10) because model confidence labels vary between runs; the final decisions did not change.

## [2026-09-13] Second read for content-blocked messages via a different OpenRouter model (supersedes previous usage numbers)
What: user chose option 3. `llm_client.OPENROUTER_SECOND_MODELS = ("nex-agi/nex-n2.5-pro:free", "dots-studio/dots-3-note-preview:free")`; `scenarios.escalate_uncertain` uses them, in order, for OpenRouter-read messages. Before the change, the 6 unchecked messages were confirmed to have no effect on output (only message_02 raises income, has no amount, and its user has no evaluation request). Smoke-tested candidates on message_02: `google/gemma-4-31b-it:free` and `gemma-4-26b-a4b-it:free` returned 429 upstream; nex and dots returned valid schema. Cleared caches, clean run 08:09:41-08:21:55 IST.
Verified: 250 rows, 0 fallbacks, `output.csv` byte-identical to the previous run, sample eval unchanged. Second reads: 11/11 readers agree, 0 unavailable (5 OpenRouter-read messages checked by nex-n2.5-pro, 6 by deepseek-v4-flash). Usage: 242 calls (deepseek-v4-flash 192, nemotron 45, nex-n2.5-pro 5), 274,466 tokens (204,948 in / 69,518 out), 1,098 tokens and 0.97 calls per request, 45 failed attempts (http_400), proxy $0.0660 / $0.000264 per request. `code.zip` rebuilt (28 files, checks pass); fresh unzip with keys unset reproduces `output.csv` with 0 calls.
