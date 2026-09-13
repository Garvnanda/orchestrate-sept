# idea.md — Approaches Considered & Why

Living record of the brainstorm that led to the locked design. Raw turn-by-turn transcript lives in `log.txt`; this is the distilled version.

## Engine architecture — options weighed

| Option | Shape | Verdict |
|---|---|---|
| A — Pure deterministic | No LLM, regex/keyword rules on messages, no image reading | Rejected: multilingual messages + image evidence (payroll letters, receipts) too weak with regex; wrong extraction poisons every downstream field |
| B — Hybrid, single-pass | Deterministic math/ranking/output + one LLM extractor call per message/image | Rejected: no second opinion on ambiguous/contradictory evidence |
| B-static | B + resolver + verifier calls, always run on every request | Rejected: wastes calls on the ~200+ requests with clean, non-conflicting data; also exactly the "fixed sequence always" pattern the prior submission's organizer feedback flagged as less agentic |
| **B-dynamic (CHOSEN)** | B + resolver call only when two sources genuinely disagree + verifier call only when confidence is low or a disagreement wasn't cleanly settled by the coded conflict-hierarchy | Cheapest correct option, zero hallucination risk in money math (that part is 100% deterministic code, always), directly answers organizer feedback's ask for uncertainty-driven specialist routing instead of a fixed pipeline |
| D — Multi-agent | LLM agents own forecasting/planning too | Rejected: highest cost/latency/risk, no benefit over B-dynamic that isn't already captured |

## Secondary decisions

- **Data layer: stdlib only** (`csv` + dict/list, `sqlite3` fallback if joins get messy). Rejected pandas (extra dependency, not needed at 25k-row scale) and duckdb (same, plus not stdlib). Fewer things that can break in someone else's grading environment.
- **Explanation generation: template → LLM rewrite, must include every fact, no new ones.** Deterministic pass builds a fixed fact list (amount safe, balance after payment, minimum kept, plan dates/amounts, spending changes, triggering rule). LLM rewrite pass must surface every item, forbidden from adding anything outside the list. Chosen over pure template (reads robotic/vague, scores worse on "usefulness") and free LLM rewrite (risks inventing/dropping a number — ungrounded, exactly what an interview would probe).
- **Validation: mandatory complete-row invariant + standalone validator pass**, non-negotiable regardless of engine choice — directly answers the prior submission's all-rows-blank failure. Validator blocks the final write on any incomplete or contract-violating row; any internal failure falls back to a safe deterministic default (`not_recommended`/`wait` + reason), never a blank cell.
- **Runtime: Python.** Matches existing `code/main.py` stub, best CSV/date/LLM-SDK ecosystem, fits stdlib-only data layer.
- **LLM provider: AgentRouter** (`base_url=https://agentrouter.org/v1`, OpenAI-compatible SDK shape, key in env var `AGENTROUTER_API_KEY`). Models available: originally 5, then narrowed to 3 (`deepseek-v4-flash`, `claude-opus-5`, `gpt-5.6-sol`), now narrowed again — **only `deepseek-v4-flash` and `glm-5.3` are up as of 2026-09-12**, rest reported down by user.
- **Model-per-role split (current, 2-model roster):** extractor=`deepseek-v4-flash` (fast/cheap, runs most often — every message/image), resolver=`deepseek-v4-flash` (runs only on detected cross-source conflicts — reuses the cheap model since only 2 exist), verifier=`glm-5.3` (runs only on low-confidence or unresolved-conflict cases, rarest — reserved so there's still a meaningful reasoning-tier step up for the hardest escalation case).
- **Escalation triggers:**
  - Resolver fires when two evidence sources (event row vs message/image, or two messages) give different amount/date/status for the same `event_id`/`request_id`.
  - Verifier fires when extractor confidence = `low` on a fact actually used in the decision, OR the resolver's suggested winner contradicts the coded conflict-resolution hierarchy (rules alone couldn't cleanly settle it).

## Post-audit decisions (2026-09-13, each approved by the user)

- **Full rework over patching.** The judge-style audit scored 3/25 exact samples and found invalid rows the old validator missed. Patching the old extractor/conflict-resolver design could not fix forecast semantics, so the forecast, decision, spending-change and validation layers were rebuilt.
- **Scenario vocabulary instead of free-form event amendments.** Messages describe situations (salary change, pay-date move, income ended), not edits to one row. A fixed scenario list maps them onto forecast rules code can apply.
- **Second read driven by uncertainty, not a fixed sequence.** Only non-high-confidence facts get a second model. Disagreement → financially safer interpretation. The old always-on resolver was removed.
- **Deterministic explanation templates** replaced the LLM rewrite. Rewrite risked invented numbers and cost 250 calls; templates match the sample wording exactly on 14/25.
- **Translation retry tier dropped.** It never unblocked a content-blocked message; OpenRouter did.
- **Cost reported with proxy list prices, clearly labeled**, because AgentRouter exposes no per-token price.
- **`glm-5.3` removed; `deepseek-v4-flash` is the only AgentRouter model** (user instruction after the clean run showed `glm-5.3` content-blocked on 8 of 10 second reads). Second reads are now a repeat `deepseek-v4-flash` call; OpenRouter stays limited to messages AgentRouter blocks.
- **Second read for content-blocked messages via a different OpenRouter free model** (user chose option 3 of: leave documented / drop unconfirmed income facts / second OpenRouter model). This relaxes the earlier "OpenRouter only for the 45 blocked first reads" rule to also cover their second reads. `nex-agi/nex-n2.5-pro:free` first, `dots-studio/dots-3-note-preview:free` backup; `google/gemma-4-*:free` rejected because it returned 429 upstream when tested.
- **Transcript: both prepared** — `log.txt` (AGENTS.md format) and a verbatim `chat_transcript.md` export; the user picks what to submit.

## Why this over the prior submission's approach

Prior submission (different problem statement) scored 0 on output.csv (all rows had blank routing decisions) and had its chat transcript rejected (summary, not a real transcript). Both failure modes are structurally prevented here: log.txt is genuinely turn-by-turn (enforced by AGENTS.md + this session), and the complete-row invariant + standalone validator make an all-blank output impossible to ship undetected. Full context in memory (`prior_submission_feedback` — see project memory, not duplicated here since it isn't code-derivable and belongs outside this repo).

## Rule

Every decision in this file was explicitly chosen or approved by the user, not decided unilaterally by the agent. See `no_unilateral_decisions` project memory / CLAUDE.md checklist. Any change to a locked decision must be re-approved before implementation changes.
