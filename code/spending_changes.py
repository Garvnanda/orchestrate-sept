import balance
import decision

MAX_CHANGES = 3
STOP_FLEX = {"stoppable", "reducible_or_stoppable"}
REDUCE_FLEX = {"reducible", "reducible_or_stoppable"}


def _event_number(event_id):
    digits = "".join(ch for ch in event_id if ch.isdigit())
    return int(digits) if digits else 0


def find_flexible_reductions(profile, resolved_events_for_user, recurring_series, forecast_events, request_date):
    """One candidate change per recurring category the user marked flexible and is willing to
    adjust (never a protected one). Cites the latest settled occurrence before request_date —
    the convention sample_requests.csv uses. Reduce is preferred over stop when both are allowed
    (least disruptive change; sample request_21 reduces a stoppable streaming plan)."""
    protect = set(profile["expense_categories_to_protect"])
    can_reduce = set(profile["expense_categories_user_is_willing_to_reduce"])
    can_stop = set(profile["expense_categories_user_is_willing_to_stop"])

    candidates = []
    for category, s in recurring_series.items():
        if category in protect:
            continue
        occurrences = [f for f in forecast_events if f["category"] == category and f["amount"] < 0]
        if not occurrences:
            continue
        settled = [
            e for e in resolved_events_for_user
            if e["category"] == category and e["status"] == "settled" and e["direction"] == "debit"
            and e["date"] <= request_date and e["amount"] is not None
        ]
        if not settled:
            continue
        rep = max(settled, key=lambda e: (e["date"], _event_number(e["event_id"])))
        floor = rep["minimum_allowed_amount"]
        per_occurrence = s.get("amount")

        if (rep["flexibility"] in REDUCE_FLEX and category in can_reduce and floor is not None
                and per_occurrence is not None and per_occurrence > floor):
            candidates.append({
                "action": "reduce_to", "event_id": rep["event_id"], "category": category,
                "new_amount": floor, "recover": (per_occurrence - floor) * len(occurrences),
                "description": rep.get("description", ""),
            })
        elif rep["flexibility"] in STOP_FLEX and category in can_stop:
            candidates.append({
                "action": "stop", "event_id": rep["event_id"], "category": category,
                "recover": sum(-f["amount"] for f in occurrences), "description": rep.get("description", ""),
            })

    candidates.sort(key=lambda c: (-c["recover"], _event_number(c["event_id"])))
    return candidates


def _apply_reductions(forecast_events, reductions):
    stop_categories = {r["category"] for r in reductions if r["action"] == "stop"}
    reduce_map = {r["category"]: r["new_amount"] for r in reductions if r["action"] == "reduce_to"}
    out = []
    for ev in forecast_events:
        if ev["category"] in stop_categories and ev["amount"] < 0:
            continue
        if ev["category"] in reduce_map and ev["amount"] < 0:
            out.append({**ev, "amount": -reduce_map[ev["category"]]})
        else:
            out.append(ev)
    return out


def format_changes(chosen):
    ordered = sorted(chosen, key=lambda c: _event_number(c["event_id"]))
    return "|".join(
        f"stop:{c['event_id']}" if c["action"] == "stop"
        else f"reduce_to:{c['event_id']}:{decision._fmt_amount(c['new_amount'])}"
        for c in ordered
    )


def try_with_spending_changes(profile, request, payment_options, current_balance,
                               user_events, recurring_series, forecast_events, baseline_result):
    """Step 12. Ranking rule 1 (complete by the deadline) outranks rule 2 (no spending changes),
    so changes are only considered when no no-change plan completes on time — i.e. the baseline
    is not_recommended. amount_safe_to_pay / earliest_date_for_full_payment stay baseline values
    (both are defined "before/without optional spending changes"). Tries 1, 2, then 3 changes."""
    if baseline_result["recommended_payment_method"] != "not_recommended":
        return baseline_result, "none", []

    accepted = set(profile["payment_methods_user_will_consider"])
    request_date = request["request_date"]
    requested_amount = request["requested_amount"]
    deadline = request["desired_completion_date"]
    min_bal = profile["minimum_balance_to_keep"]
    horizon_end = decision.horizon_end_for(request_date)

    reductions = find_flexible_reductions(profile, user_events, recurring_series, forecast_events, request_date)
    for n in range(1, min(MAX_CHANGES, len(reductions)) + 1):
        chosen = reductions[:n]
        modified_forecast = _apply_reductions(forecast_events, chosen)
        modified_timeline = balance.simulate_balance(current_balance, modified_forecast)

        candidates = []
        if ("full_payment" in accepted and request_date <= deadline
                and balance.baseline_min_balance(current_balance, modified_timeline) >= min_bal
                and balance.suffix_min_balance(current_balance, modified_timeline, request_date) - requested_amount >= min_bal):
            candidates.append((requested_amount, request_date, 1, "", "full_payment", [(request_date, requested_amount)]))

        if "installments" in accepted and profile["max_installment_months"] is not None:
            for opt in payment_options:
                if opt["payment_method"] != "installments" or opt["number_of_payments"] > profile["max_installment_months"]:
                    continue
                plan = decision._build_installment_plan(opt)
                if plan[-1][0] > deadline:
                    continue
                in_horizon = [(d, a) for d, a in plan if d <= horizon_end]
                if balance.schedule_min_balance(current_balance, modified_forecast, in_horizon) >= min_bal:
                    candidates.append((opt["total_payable_amount"], plan[0][0], len(plan), opt["payment_option_id"], "installments", plan))

        if candidates:
            _, _, _, _, method, plan = min(candidates)
            return {
                **baseline_result,
                "affordability_status": "affordable_with_plan",
                "recommended_payment_method": method,
                "payment_plan": "|".join(f"{d}:{decision._fmt_amount(a)}" for d, a in plan),
            }, format_changes(chosen), chosen

    return baseline_result, "none", []
