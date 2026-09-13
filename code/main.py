import csv
import os
import sys

import balance
import data_loader
import decision
import explanation
import forecast
import scenarios
import spending_changes
import validate

COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation",
]


def build_context(ds, dataset_dir=data_loader.DATASET_DIR):
    """Shared, request-independent stages: read images and messages (LLM, cached), prepare events."""
    blank_amounts, unresolved = scenarios.extract_blank_amounts(ds, dataset_dir)
    scenario_results = scenarios.escalate_uncertain(ds, scenarios.extract_message_scenarios(ds))
    return {
        "blank_amounts": blank_amounts,
        "unresolved_blank": set(unresolved),
        "scenarios": scenario_results,
        "events_by_user": forecast.prepare_events(ds, blank_amounts),
        "freq": forecast.description_frequency(ds),
    }


def decide_request(ds, req, ctx, cfg=None):
    """Every structured output field for one request. No LLM call happens here."""
    profile = ds.profiles[req["user_id"]]
    user_events = ctx["events_by_user"].get(req["user_id"], [])
    missing = [e["event_id"] for e in user_events if e["event_id"] in ctx["unresolved_blank"]]
    if missing:
        raise ValueError(f"blank amount could not be read from the linked image for {missing}")
    failed_msgs = [m["message_id"] for m in ds.messages
                   if m["user_id"] == req["user_id"] and ctx["scenarios"].get(m["message_id"], {}).get("error")]
    if failed_msgs:
        raise ValueError(f"message evidence could not be read for {failed_msgs}")

    facts = forecast.facts_for(ds, ctx["scenarios"], req["user_id"], req["request_date"])
    current = profile["current_available_balance"]
    events, series = forecast.build_forecast(ds, user_events, req, facts, ctx["freq"], cfg)
    timeline = balance.simulate_balance(current, events)
    options = ds.payment_options_by_request.get(req["request_id"], [])

    baseline = decision.decide(profile, req, options, current, events, timeline)
    result, changes, chosen = spending_changes.try_with_spending_changes(
        profile, req, options, current, user_events, series, events, baseline
    )
    return {"profile": profile, "result": result, "changes": changes, "chosen": chosen,
            "facts": facts, "events": events, "timeline": timeline}


def build_row(ds, req, ctx):
    d = decide_request(ds, req, ctx)
    result = d["result"]
    return {
        "request_id": req["request_id"],
        "amount_safe_to_pay": decision._fmt_amount(result["amount_safe_to_pay"]),
        "affordability_status": result["affordability_status"],
        "recommended_payment_method": result["recommended_payment_method"],
        "payment_plan": result["payment_plan"],
        "earliest_date_for_full_payment": result["earliest_date_for_full_payment"],
        "spending_changes_needed": d["changes"],
        "decision_explanation": explanation.explain(req, d["profile"], result, d["chosen"]),
    }


def _write(rows, output_path):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _request_ids_raw(dataset_dir):
    with open(os.path.join(dataset_dir, "requests.csv"), newline="", encoding="utf-8") as f:
        return [r["request_id"] for r in csv.DictReader(f)]


def run(dataset_dir=data_loader.DATASET_DIR, output_path=os.path.join(data_loader.REPO_ROOT, "output.csv")):
    try:
        ds = data_loader.load_all(dataset_dir)
        ctx = build_context(ds, dataset_dir)
    except Exception as e:
        # A shared stage failed, so no request can be evaluated. Still honor the complete-row
        # invariant, then exit non-zero so the failure cannot go unnoticed.
        request_ids = _request_ids_raw(dataset_dir)
        _write([validate.safe_default_row(rid, f"pipeline stage failed: {e}") for rid in request_ids], output_path)
        print(f"FAILED: shared pipeline stage raised {type(e).__name__}: {e}", file=sys.stderr)
        print(f"wrote {len(request_ids)} safe-default rows to {output_path}", file=sys.stderr)
        raise SystemExit(1)

    rows = []
    fallbacks = []
    for req in ds.requests:
        options = ds.payment_options_by_request.get(req["request_id"], [])
        try:
            row = build_row(ds, req, ctx)
            validate.validate_row(row, req, options, ds.profiles[req["user_id"]], ds.events_by_id)
        except Exception as e:
            row = validate.safe_default_row(req["request_id"], str(e))
            fallbacks.append((req["request_id"], f"{type(e).__name__}: {e}"))
        rows.append(row)

    assert len(rows) == len(ds.requests), f"expected {len(ds.requests)} rows, built {len(rows)}"
    assert len({r["request_id"] for r in rows}) == len(rows), "duplicate request_id in output"
    _write(rows, output_path)

    for rid, reason in fallbacks:
        print(f"WARNING: {rid} used the safe-default row — {reason}", file=sys.stderr)
    print(f"OK: wrote {len(rows)} rows to {output_path}, {len(fallbacks)} used the safe-default fallback")
    return len(fallbacks)


if __name__ == "__main__":
    run()
