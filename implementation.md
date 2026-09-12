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
- [ ] 8. Verifier call (advisory, logged only) — fires on low-confidence-used-fact or resolver/hierarchy mismatch
- [ ] 9. Financial state reconstruction per user — recurring vs one-time, pending/settled/cancelled handling, dedupe linked events, confirmed-salary-on-settlement-date
- [ ] 10. 90-day forward balance forecast engine
- [ ] 11. Decision engine — `amount_safe_to_pay`, `affordability_status`, method eligibility filter, plan ranking (6 tie-break rules)
- [ ] 12. Spending-changes generator — flexible-only, stop/reduce_to mutual exclusivity, max 3
- [ ] 13. Explanation generator — deterministic fact list → LLM rewrite pass (must-include-all, no-new-facts constraint enforced)
- [ ] 14. Output writer — draft row per request
- [ ] 15. Standalone validator — full contract check per row, blocks write, safe-default fallback wired in from step 1 onward (not bolted on at the end)
- [ ] 16. Dry run against `dataset/sample_requests.csv` — compare against its filled columns, sanity-check divergences (not literal grading, format/style reference only per problem_statement.md)
- [ ] 17. Full run on `dataset/requests.csv` → root-level `output.csv`, confirm 250 rows + header, exact column order
- [ ] 18. `evaluation/usage_report.md` — generate from the actual final full-dataset run's real token/call counts per model, not estimated/fabricated numbers
- [ ] 19. Package `code.zip` — code/, README with setup+run instructions, `evaluation/` folder, confirm no `.env`/secrets included
- [ ] 20. Judge-interview prep — pick one fully-traced example request (message-in → output-row-out, name what each stage consumed/produced), 3 defendable numbers/thresholds with evidence from the actual run, one monitoring signal + drift action (e.g. validator-fallback rate, or verifier-escalation rate vs total requests)

## Blocking items — RESOLVED

- Model IDs confirmed: extractor=`deepseek-v4-flash`, resolver=`gpt-5.6-sol`, verifier=`claude-opus-5`. Only these 3 models available for now.
- `.env` variable name confirmed: `AGENTROUTER_API_KEY`.
- Step 4 (AgentRouter client wrapper) is now unblocked.
