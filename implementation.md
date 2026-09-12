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

## Blocking items — RESOLVED

- Model IDs confirmed: extractor=`deepseek-v4-flash`, resolver=`gpt-5.6-sol`, verifier=`claude-opus-5`. Only these 3 models available for now.
- `.env` variable name confirmed: `AGENTROUTER_API_KEY`.
- Step 4 (AgentRouter client wrapper) is now unblocked.
