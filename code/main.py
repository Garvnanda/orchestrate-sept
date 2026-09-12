import csv

import data_loader
import decision
import evidence
import explanation
import reconstruct
import spending_changes
import validate

COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation",
]


def build_row(ds, req, events_by_user, exp_cache):
    profile = ds.profiles[req["user_id"]]
    user_events = events_by_user.get(req["user_id"], [])
    series = reconstruct.detect_recurring_series(user_events, req["request_date"])
    forecast = reconstruct.project_forecast_events(req["request_date"], user_events, series)
    timeline = reconstruct.simulate_balance(profile["current_available_balance"], forecast)
    options = ds.payment_options_by_request.get(req["request_id"], [])

    baseline = decision.decide(profile, req, options, profile["current_available_balance"], forecast, timeline)
    result, changes = spending_changes.try_with_spending_changes(
        profile, req, options, profile["current_available_balance"], user_events, series, forecast, baseline
    )
    explanation_text = explanation.generate_explanation(req["request_id"], req, profile, result, changes, exp_cache)

    return {
        "request_id": req["request_id"],
        "amount_safe_to_pay": decision._fmt_amount(result["amount_safe_to_pay"]),
        "affordability_status": result["affordability_status"],
        "recommended_payment_method": result["recommended_payment_method"],
        "payment_plan": result["payment_plan"],
        "earliest_date_for_full_payment": result["earliest_date_for_full_payment"],
        "spending_changes_needed": changes,
        "decision_explanation": explanation_text,
    }


def run(dataset_dir="dataset", output_path="output.csv"):
    ds = data_loader.load_all(dataset_dir)
    amount_overrides = evidence.resolve_blank_amounts(ds, dataset_dir)
    image_facts = evidence.extract_all_images(ds, dataset_dir)
    message_facts = evidence.extract_all_messages(ds)
    _, events_by_user = reconstruct.build_all(ds, message_facts, image_facts, amount_overrides)
    exp_cache = explanation._load_cache()

    rows = []
    fallback_count = 0
    for req in ds.requests:
        options = ds.payment_options_by_request.get(req["request_id"], [])
        try:
            row = build_row(ds, req, events_by_user, exp_cache)
            validate.validate_row(row, req, options)
        except Exception as e:
            row = validate.safe_default_row(req["request_id"], str(e))
            fallback_count += 1
        rows.append(row)

    assert len(rows) == len(ds.requests), f"expected {len(ds.requests)} rows, built {len(rows)}"

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"OK: wrote {len(rows)} rows to {output_path}, {fallback_count} used the safe-default fallback")
    return fallback_count


if __name__ == "__main__":
    run()
