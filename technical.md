# technical.md — Architecture & Design Reference

Status: reflects the post-audit rework of 2026-09-13 (full rework approved by the user; explanation templates approved; proxy-price cost basis approved). Earlier designs (extractor → conflict resolver → verifier → LLM explanation rewrite, in `evidence.py`/`conflicts.py`/`reconstruct.py`) were deleted; see `done.md` for why.

## Stack

- Python, stdlib for all data processing. Third-party: `openai` (OpenAI-compatible client) and `python-dotenv`.
- AgentRouter (`AGENTROUTER_BASE_URL`, `AGENTROUTER_API_KEY`, `AGENTROUTER_USER_AGENT` — the gateway rejects requests without a custom User-Agent): `deepseek-v4-flash` only (`glm-5.3` removed on the user's instruction, 2026-09-13).
- OpenRouter (`OPENROUTER_API_KEY`): `nvidia/nemotron-3-super-120b-a12b:free`, used only for messages AgentRouter's moderation blocks; `nex-agi/nex-n2.5-pro:free` / `dots-studio/dots-3-note-preview:free` only for second reads of those blocked messages.
- Entry point: `python code/main.py` from the repository root (paths are anchored to the repo root, so any working directory works).

## Principle

Models read. Code decides. A model never produces a number that reaches `output.csv` directly and never writes an output field. Its only output is a list of facts in a fixed schema, normalized and range-checked at the boundary (`scenarios.normalize_scenarios`); anything outside the vocabulary is dropped.

## Pipeline

```
data_loader ─► scenarios (LLM, cached) ─► forecast ─► balance ─► decision ─► spending_changes ─► explanation ─► validate ─► output.csv
```

Shared stages (run once): `build_context` in `main.py`.
1. **Blank amounts** (`scenarios.extract_blank_amounts`). Events with a blank `amount` are resolved from the linked image: `deepseek-v4-flash`. Cache key: sha256 of the image bytes. An unresolved blank is never treated as 0 — requests of that user get the safe-default row with the reason.
2. **Message scenarios** (`scenarios.extract_message_scenarios`). Each message is read once into a list of facts from a fixed vocabulary of ~24 scenarios (salary change, temporary salary, pay-date move, income ended/resumes, first salary, foreign-currency salary, arrears, invoice confirmed, expense percent change, new recurring expense, failed debit that will retry, …), each with `confidence`. Attempt order: `deepseek-v4-flash` → OpenRouter (only reached when AgentRouter rejects the content). Cache key: `message_id` + sha256 of the text, so an edited message is re-read.
3. **Second read** (`scenarios.escalate_uncertain`). Only messages whose facts are not all `high` confidence get a second, independent `deepseek-v4-flash` call. Same model, so this catches unstable readings, not model bias. Messages first read by OpenRouter (AgentRouter rejects them) get their second read from a different OpenRouter free model family: `nex-agi/nex-n2.5-pro:free`, then `dots-studio/dots-3-note-preview:free` if rate-limited. Agree → keep. Disagree → financially safer interpretation: unconfirmed income-raising facts are dropped. Second read unavailable → first read kept and logged. Everything goes to `evaluation/escalation_log.json`.
4. **Event preparation** (`forecast.prepare_events`). Superseded lifecycle predecessors (rows named by another row's `linked_event_id`) are dropped; blank amounts filled; original currency retained for dated FX.

Per request (`main.decide_request`, no model calls):
5. **Forecast** (`forecast.build_forecast`), horizon 90 days from `request_date`:
   - Income: payroll stream (mode amount, mode pay day); a "final" payslip stops the stream; irregular income (bonus, commission, refund, lottery, investment gain) is never projected; recurring freelance side income counted at its minimum observed amount.
   - Expenses: recurring series from settled history with common descriptions (dataset frequency ≥ 20), anchored on the latest settled event in the category, median amount estimator.
   - Pending/scheduled debits reserved; pending credits ignored.
   - Message scenarios applied on top.
   - Foreign currency converted with the exact dated `exchange_rates.csv` row (`currency.py`); a missing rate raises instead of guessing.
   - Intraday order: debits before credits, and a user payment is placed after that day's flows.
6. **Balance** (`balance.py`): running balance; `suffix_min_balance` = lowest balance a payment on date D would see; `find_earliest_safe_date` returns `None` if the forecast breaches the minimum even without paying.
7. **Decision** (`decision.py`):
   - `amount_safe_to_pay` = clamp(suffix_min(request_date) − minimum_balance_to_keep, 0, requested). 0 if the baseline already breaches.
   - Candidates: full payment, partial (two payments, second on earliest safe date), each supplied installment option, wait. Filtered by the user's accepted methods, `max_installment_months`, `allows_partial_payment`, the desired completion date, and a full-schedule balance check.
   - Ranking: completes by deadline → no spending changes → lowest total cost → earliest start → fewest payments → lowest option id.
8. **Spending changes** (`spending_changes.py`): only when the baseline is `not_recommended`. Only non-protected, flexible, permitted categories; cites the latest settled event of the series; prefers `reduce_to` over `stop`; at most 3; output in event order. The upgraded plan must pass the same deadline and balance checks.
9. **Explanation** (`explanation.py`): deterministic templates per outcome, filled from the computed result. No model, so no invented numbers.
10. **Validation** (`validate.py`), before the write: enums and method/status mapping, method accepted by the user, plan shape per method (full = one payment on the earliest date, partial = two payments summing to the request, installments = exact supplied schedule), dates ≥ `request_date`, `not_recommended` ⇒ plan `none`, `affordable_now` ⇒ no changes, spending changes reference real events in non-protected categories the user is willing to stop/reduce, with the right flexibility, `reduce_to` not below `minimum_allowed_amount`, and never stop + reduce on the same event. A failing row is replaced by `safe_default_row` and the reason goes to stderr.
11. **Output** (`main.run`): exactly one row per `request_id`, asserted. If a shared stage fails, every request gets a safe-default row and the process exits 1.

## Evaluation on public samples

`python code/evaluate_samples.py -v` runs the full pipeline on `dataset/sample_requests.csv` and compares 7 fields. Samples are never used in prompts. The design choices listed above (median estimator, anchoring, intraday order, 90-day horizon, deadline gate) were calibrated against these 25 rows, so the score is in-sample and optimistic.

| Field | Before rework | After rework |
|---|---:|---:|
| affordability_status | 13/25 | 20/25 |
| recommended_payment_method | 15/25 | 20/25 |
| payment_plan | 14/25 | 20/25 |
| earliest_date_for_full_payment | 8/25 | 17/25 |
| spending_changes_needed | 20/25 | 20/25 |
| decision_explanation (exact wording) | ~0/25 | 14/25 |
| amount_safe_to_pay (exact) | — | 3/25 |
| all fields exact | 3/25 | 3/25 |

Known limit: exact `amount_safe_to_pay` rarely matches, because the organizer's variable-spend estimator is not recoverable from 25 rows (example: request_08 differs by €0.98). Tuning further would overfit the samples, so calibration stopped there.

## Monitoring signals

- Safe-default fallback count printed by `main.py` (target 0).
- `escalation_log.json` outcomes: a rise in "readers disagree" means evidence reading got less reliable.
- `usage_log.json` `failed_attempts` per model: a rise in `http_4xx` means provider moderation changed.
