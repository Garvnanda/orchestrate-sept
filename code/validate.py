import decision

VALID_STATUS = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
VALID_METHOD = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}

REQUIRED_NONEMPTY = [
    "request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "spending_changes_needed", "decision_explanation",
]


class ValidationError(Exception):
    pass


def _parse_plan(plan_str):
    if plan_str == "none":
        return []
    entries = []
    for part in plan_str.split("|"):
        date_str, amount_str = part.split(":")
        entries.append((date_str, float(amount_str)))
    return entries


def safe_default_row(request_id, reason):
    return {
        "request_id": request_id,
        "amount_safe_to_pay": "0",
        "affordability_status": "not_affordable",
        "recommended_payment_method": "not_recommended",
        "payment_plan": "none",
        "earliest_date_for_full_payment": "",
        "spending_changes_needed": "none",
        "decision_explanation": (
            f"Unable to safely evaluate this request due to an internal error ({reason}); "
            "defaulting to the safest recommendation."
        ),
    }


def validate_row(row, request, payment_options_for_request):
    for field in REQUIRED_NONEMPTY:
        if row.get(field) in (None, ""):
            raise ValidationError(f"{field} is empty")

    amount_safe_to_pay = float(row["amount_safe_to_pay"])
    if not (-1e-6 <= amount_safe_to_pay <= request["requested_amount"] + 1e-6):
        raise ValidationError(
            f"amount_safe_to_pay {amount_safe_to_pay} out of bounds [0, {request['requested_amount']}]"
        )

    if row["affordability_status"] not in VALID_STATUS:
        raise ValidationError(f"bad affordability_status {row['affordability_status']!r}")
    if row["recommended_payment_method"] not in VALID_METHOD:
        raise ValidationError(f"bad recommended_payment_method {row['recommended_payment_method']!r}")

    if row["affordability_status"] == "affordable_now" and row["earliest_date_for_full_payment"] != request["request_date"]:
        raise ValidationError("affordable_now requires earliest_date_for_full_payment == request_date")

    plan = _parse_plan(row["payment_plan"])
    dates = [d for d, _ in plan]
    if dates != sorted(dates):
        raise ValidationError("payment_plan not chronological")

    if row["recommended_payment_method"] == "partial_payment":
        if len(plan) != 2:
            raise ValidationError("partial_payment must have exactly 2 payments")
        total = plan[0][1] + plan[1][1]
        if abs(total - request["requested_amount"]) > 0.01:
            raise ValidationError(f"partial_payment total {total} != requested_amount {request['requested_amount']}")

    if row["recommended_payment_method"] == "installments":
        matched = any(
            len(opt_plan := decision._build_installment_plan(opt)) == len(plan)
            and all(d1 == d2 and abs(a1 - a2) < 0.01 for (d1, a1), (d2, a2) in zip(opt_plan, plan))
            for opt in payment_options_for_request if opt["payment_method"] == "installments"
        )
        if not matched:
            raise ValidationError("installments plan does not match any supplied payment option")

    changes = row["spending_changes_needed"]
    if changes != "none":
        parts = changes.split("|")
        if len(parts) > 3:
            raise ValidationError("more than 3 spending changes")
        stop_ids, reduce_ids = set(), set()
        for p in parts:
            if p.startswith("stop:"):
                stop_ids.add(p.split(":", 1)[1])
            elif p.startswith("reduce_to:"):
                reduce_ids.add(p.split(":", 2)[1])
            else:
                raise ValidationError(f"bad spending change entry {p!r}")
        if stop_ids & reduce_ids:
            raise ValidationError("stop and reduce_to target the same event")

    return True
