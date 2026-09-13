import datetime

import decision

VALID_STATUS = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
VALID_METHOD = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
IMMEDIATE_METHODS = {"full_payment", "partial_payment", "installments"}
STATUS_FOR_METHOD = {
    "partial_payment": {"affordable_with_plan"},
    "installments": {"affordable_with_plan"},
    "wait": {"affordable_later"},
    "not_recommended": {"not_affordable"},
    "full_payment": {"affordable_now", "affordable_with_plan"},
}
STOP_FLEX = {"stoppable", "reducible_or_stoppable"}
REDUCE_FLEX = {"reducible", "reducible_or_stoppable"}

REQUIRED_NONEMPTY = [
    "request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "spending_changes_needed", "decision_explanation",
]


class ValidationError(Exception):
    pass


def _iso(value, field):
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValidationError(f"{field} is not a YYYY-MM-DD date: {value!r}")


def _parse_plan(plan_str):
    if plan_str == "none":
        return []
    entries = []
    for part in plan_str.split("|"):
        date_str, sep, amount_str = part.partition(":")
        if not sep:
            raise ValidationError(f"payment_plan entry {part!r} is not date:amount")
        amount = float(amount_str)
        if amount <= 0:
            raise ValidationError(f"payment_plan amount must be positive: {part!r}")
        entries.append((_iso(date_str, "payment_plan date"), amount))
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


def _check_spending_changes(changes, profile, events_by_id):
    if changes == "none":
        return
    parts = changes.split("|")
    if len(parts) > 3:
        raise ValidationError("more than 3 spending changes")
    stop_ids, reduce_ids = set(), set()
    for p in parts:
        if p.startswith("stop:"):
            action, event_id, new_amount = "stop", p[len("stop:"):], None
            stop_ids.add(event_id)
        elif p.startswith("reduce_to:"):
            _, event_id, amount_str = p.split(":", 2)
            action, new_amount = "reduce_to", float(amount_str)
            reduce_ids.add(event_id)
        else:
            raise ValidationError(f"bad spending change entry {p!r}")

        if events_by_id is None or profile is None:
            continue
        event = events_by_id.get(event_id)
        if event is None:
            raise ValidationError(f"spending change references unknown event {event_id}")
        if event["user_id"] != profile["user_id"]:
            raise ValidationError(f"spending change event {event_id} belongs to another user")
        if event["direction"] != "debit":
            raise ValidationError(f"spending change event {event_id} is not an expense")
        if event["category"] in profile["expense_categories_to_protect"]:
            raise ValidationError(f"spending change targets protected category {event['category']}")
        if action == "stop":
            if event["flexibility"] not in STOP_FLEX or event["category"] not in profile["expense_categories_user_is_willing_to_stop"]:
                raise ValidationError(f"stop:{event_id} is not a stoppable category the user accepts")
        else:
            if event["flexibility"] not in REDUCE_FLEX or event["category"] not in profile["expense_categories_user_is_willing_to_reduce"]:
                raise ValidationError(f"reduce_to:{event_id} is not a reducible category the user accepts")
            floor = event["minimum_allowed_amount"]
            if new_amount <= 0 or (floor is not None and new_amount < floor - 1e-6):
                raise ValidationError(f"reduce_to:{event_id} amount {new_amount} below minimum_allowed_amount {floor}")
    if stop_ids & reduce_ids:
        raise ValidationError("stop and reduce_to target the same event")


def validate_row(row, request, payment_options_for_request, profile=None, events_by_id=None):
    for field in REQUIRED_NONEMPTY:
        if row.get(field) in (None, ""):
            raise ValidationError(f"{field} is empty")

    requested = request["requested_amount"]
    request_date = request["request_date"]
    status = row["affordability_status"]
    method = row["recommended_payment_method"]
    changes = row["spending_changes_needed"]
    earliest = row["earliest_date_for_full_payment"]

    amount_safe_to_pay = float(row["amount_safe_to_pay"])
    if not (-1e-6 <= amount_safe_to_pay <= requested + 1e-6):
        raise ValidationError(f"amount_safe_to_pay {amount_safe_to_pay} out of bounds [0, {requested}]")
    if status not in VALID_STATUS:
        raise ValidationError(f"bad affordability_status {status!r}")
    if method not in VALID_METHOD:
        raise ValidationError(f"bad recommended_payment_method {method!r}")
    if status not in STATUS_FOR_METHOD[method]:
        raise ValidationError(f"{method} cannot carry affordability_status {status}")
    if earliest and _iso(earliest, "earliest_date_for_full_payment") < request_date:
        raise ValidationError("earliest_date_for_full_payment is before request_date")

    accepted = set(profile["payment_methods_user_will_consider"]) if profile else None
    if accepted is not None:
        if method in IMMEDIATE_METHODS and method not in accepted:
            raise ValidationError(f"{method} is not a method the user will consider")
        if method == "wait" and "full_payment" not in accepted:
            raise ValidationError("wait requires the user to accept full_payment")

    plan = _parse_plan(row["payment_plan"])
    dates = [d for d, _ in plan]
    if dates != sorted(dates):
        raise ValidationError("payment_plan not chronological")
    if method == "not_recommended":
        if plan or changes != "none":
            raise ValidationError("not_recommended must have payment_plan=none and no spending changes")
    elif not plan:
        raise ValidationError(f"{method} requires a payment_plan")

    if status == "affordable_now":
        if earliest != request_date:
            raise ValidationError("affordable_now requires earliest_date_for_full_payment == request_date")
        if changes != "none":
            raise ValidationError("affordable_now cannot need spending changes")
    if method == "full_payment":
        if len(plan) != 1 or plan[0][0] != request_date or abs(plan[0][1] - requested) > 0.01:
            raise ValidationError("full_payment plan must be one payment of requested_amount on request_date")
        if status == "affordable_with_plan" and changes == "none":
            raise ValidationError("full_payment is only affordable_with_plan when spending changes are applied")
    if method == "wait":
        if not earliest or len(plan) != 1 or plan[0][0] != earliest or abs(plan[0][1] - requested) > 0.01:
            raise ValidationError("wait plan must be one full payment on earliest_date_for_full_payment")
    if method == "partial_payment":
        if not request["allows_partial_payment"]:
            raise ValidationError("partial_payment on a request that does not allow it")
        if len(plan) != 2:
            raise ValidationError("partial_payment must have exactly 2 payments")
        if not (0 < amount_safe_to_pay < requested):
            raise ValidationError("partial_payment requires 0 < amount_safe_to_pay < requested_amount")
        if plan[0][0] != request_date or abs(plan[0][1] - amount_safe_to_pay) > 0.01:
            raise ValidationError("partial_payment first payment must be amount_safe_to_pay on request_date")
        if plan[1][0] != earliest or earliest > request["desired_completion_date"]:
            raise ValidationError("partial_payment second payment must be on earliest_date, on/before the deadline")
        if abs(plan[0][1] + plan[1][1] - requested) > 0.01:
            raise ValidationError("partial_payment payments must sum to requested_amount")
    if method == "installments":
        matched = any(
            len(opt_plan := decision._build_installment_plan(opt)) == len(plan)
            and all(d1 == d2 and abs(a1 - a2) < 0.01 for (d1, a1), (d2, a2) in zip(opt_plan, plan))
            for opt in payment_options_for_request if opt["payment_method"] == "installments"
        )
        if not matched:
            raise ValidationError("installments plan does not match any supplied payment option")

    _check_spending_changes(changes, profile, events_by_id)
    return True
