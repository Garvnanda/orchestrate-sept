# implementation.md — Build Checklist (forward-looking)

Ordered task list. Check items off as they're actually built and verified — move the corresponding entry to `done.md` with how it was verified, don't just tick here. Do not skip ahead out of order without flagging why.

- [x] 0. Scaffold `.env.example` (var names only, no real values) + confirm real `.env` is gitignored (already done: `log.txt`, `.env`, `__pycache__/` in `.gitignore`)
- [x] 1. Data loader — parse all `dataset/*.csv` into plain dicts/lists (stdlib `csv`), join by `user_id`/`request_id`/`related_event_id`
- [x] 2. Blank-amount resolution — `code/evidence.py` (image → extractor call → cached JSON)
- [x] 3. Currency normalization module — exact dated-rate lookup, no invented rates
- [x] 4. AgentRouter client wrapper — OpenAI-compatible SDK, `base_url`, schema-enforced structured output, retry-on-schema-failure, response caching to local JSON keyed by message_id/image_id
- [x] 5. Evidence extractor — `code/evidence.py`, all 215 messages + 16 images extracted, 0 failures (4-tier fallback: AgentRouter extractor/verifier direct, translated retry, OpenRouter last resort)
- [x] 6. Conflict detector (coded) — `code/conflicts.py`, `detect_conflicts()`/`build_facts_by_event()`
- [x] 7. Resolver call + coded conflict-resolution hierarchy — `code/conflicts.py`, `resolve_by_hierarchy()` + `resolve_conflict()` (hierarchy always wins; resolver call fires on every detected conflict for a second opinion)
- [x] 8. Verifier call (advisory, logged only) — `conflicts.run_verifier_escalations()`, fires on low-confidence-used-fact or resolver/hierarchy mismatch, results cached and saved to `evaluation/verifier_log.json`
- [x] 9. Financial state reconstruction per user — `code/reconstruct.py`, `build_resolved_events()` + `detect_recurring_series()`
- [x] 10. 90-day forward balance forecast engine — `code/reconstruct.py`, `project_forecast_events()` + `simulate_balance()` + `min_balance_up_to()`
- [x] 11. Decision engine — `code/decision.py`: `compute_capacity()`, `build_candidates()`, `rank_candidates()`, `decide()`
- [x] 12. Spending-changes generator — `code/spending_changes.py`: `find_flexible_reductions()` + `try_with_spending_changes()`
- [x] 13. Explanation generator — `code/explanation.py`: template fact list → LLM rewrite, numeric-completeness guard falls back to template if the rewrite drops/invents a number
- [x] 14. Output writer — `code/main.py`, `build_row()` + `run()`
- [x] 15. Standalone validator — `code/validate.py`, `validate_row()` + `safe_default_row()`
- [x] 16. Dry run against `dataset/sample_requests.csv` — request_01 exact match, request_02 documented divergence (see technical.md), done as part of step 11's build
- [x] 17. Full run on `dataset/requests.csv` → root-level `output.csv`, 250 rows + header, exact column order, 0 safe-default fallbacks on the final tracked run
- [x] 18. `code/evaluation/usage_report.md` — real numbers from a full cache-clear + fresh tracked rerun (490 calls, 459,716 tokens)
- [x] 19. Package `code.zip` — code/ (incl. `evaluation/`), README, requirements.txt, .env.example, design docs. Verified: no `.env`, no `log.txt`, no `dataset/`, no `__pycache__`
- [x] 20. Judge-interview prep — see done.md's final entry: full `request_01` trace, 3 defendable numbers, 1 monitoring signal

## Post-audit rework (2026-09-13) — approved by the user as "Full rework"

The audit found only 3/25 samples fully matching, 2 invalid rows hidden by a weak validator, a cwd-dependent dataset path, and an unread blank amount (image_09). Steps 2, 5-13 and 15 above were rebuilt; the old modules were deleted.

- [x] R1. Repo-root anchored paths in `data_loader.py`; typed sample fields
- [x] R2. `scenarios.py` — message scenario vocabulary, schema normalization, hash-keyed caches, uncertainty-triggered second read
- [x] R3. `scenarios.extract_blank_amounts` — image reader with verifier fallback (fixes image_09)
- [x] R4. `forecast.py` — payroll stream, recurring expenses, pending items, scenario application, intraday order
- [x] R5. `balance.py` — suffix-min semantics (payday off-by-one fixed), baseline-breach rule, self-test
- [x] R6. `decision.py` — deadline gate on every candidate, capacity 0 on baseline breach
- [x] R7. `spending_changes.py` — rewritten; only when baseline is not_recommended
- [x] R8. `explanation.py` — deterministic templates (user-approved), self-test on sample wording
- [x] R9. `validate.py` — strict contract incl. accepted methods and spending-change validity
- [x] R10. `evaluate_samples.py` — 7-field sample scorer
- [x] R11. `main.py` — shared-stage failure writes safe-default rows + exit 1; per-row fallback warnings
- [x] R12. Clean cache-cleared tracked run → `output.csv` + regenerated `usage_report.md` (proxy prices, labeled)
- [x] R13. `chat_transcript.md` verbatim export (user will choose it or `log.txt`)
- [x] R14. Rebuild `code.zip`, fresh-unzip run without keys, compare output

## Blocking items — RESOLVED

Note: steps 2, 5-13, 15 and 18 above describe the pre-rework design (`evidence.py`, `conflicts.py`, `reconstruct.py`, LLM explanation rewrite, 490-call usage numbers), all deleted or superseded by R1-R14. The model list below is historical; the current roster is in technical.md (`deepseek-v4-flash` on AgentRouter, OpenRouter free models for content-blocked messages).

- Model IDs confirmed (historical): extractor=`deepseek-v4-flash`, resolver=`gpt-5.6-sol`, verifier=`claude-opus-5`.
- `.env` variable name confirmed: `AGENTROUTER_API_KEY`.
- Step 4 (AgentRouter client wrapper) is now unblocked.
