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
