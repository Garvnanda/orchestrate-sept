import datetime

import balance

HORIZON_DAYS = 90


def _fmt_amount(a):
    r = round(a, 2)
    return str(int(r)) if r == int(r) else f"{r:.2f}"


def horizon_end_for(request_date):
    return (balance.parse_date(request_date) + datetime.timedelta(days=HORIZON_DAYS)).isoformat()


def compute_capacity(profile, request, current_balance, timeline):
    """amount_safe_to_pay and earliest_date_for_full_payment — both computed before any
    optional spending changes, independent of the user's payment-method preferences."""
    request_date = request["request_date"]
    horizon_end = horizon_end_for(request_date)
    if balance.baseline_min_balance(current_balance, timeline) < profile["minimum_balance_to_keep"]:
        amount_safe_to_pay = 0.0
    else:
        room = balance.suffix_min_balance(current_balance, timeline, request_date) - profile["minimum_balance_to_keep"]
        amount_safe_to_pay = max(0.0, min(round(room, 2), request["requested_amount"]))
    earliest_date = balance.find_earliest_safe_date(
        current_balance, timeline, profile["minimum_balance_to_keep"],
        request["requested_amount"], request_date, horizon_end,
    )
    return amount_safe_to_pay, earliest_date, horizon_end


def _build_installment_plan(opt):
    plan = []
    d = balance.parse_date(opt["first_payment_date"])
    freq = datetime.timedelta(days=opt["payment_frequency_days"] or 0)
    for _ in range(opt["number_of_payments"]):
        plan.append((d.isoformat(), opt["payment_amount"]))
        d += freq
    return plan


def build_candidates(profile, request, payment_options, current_balance, forecast_events, timeline,
                      amount_safe_to_pay, earliest_date, horizon_end):
    accepted = set(profile["payment_methods_user_will_consider"])
    request_date = request["request_date"]
    requested_amount = request["requested_amount"]
    deadline = request["desired_completion_date"]
    min_bal = profile["minimum_balance_to_keep"]
    candidates = []

    if "full_payment" in accepted and earliest_date == request_date:
        candidates.append({
            "method": "full_payment", "plan": [(request_date, requested_amount)],
            "completes_by_deadline": request_date <= deadline, "total_paid": requested_amount,
            "start_date": request_date, "num_payments": 1, "option_id": None,
        })

    if (request["allows_partial_payment"] and "partial_payment" in accepted
            and 0 < amount_safe_to_pay < requested_amount and earliest_date is not None
            and earliest_date <= deadline):
        candidates.append({
            "method": "partial_payment",
            "plan": [(request_date, amount_safe_to_pay), (earliest_date, requested_amount - amount_safe_to_pay)],
            "completes_by_deadline": True, "total_paid": requested_amount,
            "start_date": request_date, "num_payments": 2, "option_id": None,
        })

    if "installments" in accepted and profile["max_installment_months"] is not None:
        for opt in payment_options:
            if opt["payment_method"] != "installments":
                continue
            if opt["number_of_payments"] > profile["max_installment_months"]:
                continue
            plan = _build_installment_plan(opt)
            extra_payments = [(d, a) for d, a in plan if d <= horizon_end]
            if balance.schedule_min_balance(current_balance, forecast_events, extra_payments) < min_bal:
                continue
            last_date = plan[-1][0]
            candidates.append({
                "method": "installments", "plan": plan,
                "completes_by_deadline": last_date <= deadline, "total_paid": opt["total_payable_amount"],
                "start_date": plan[0][0], "num_payments": len(plan), "option_id": opt["payment_option_id"],
            })

    if "full_payment" in accepted and earliest_date is not None and earliest_date != request_date:
        candidates.append({
            "method": "wait", "plan": [(earliest_date, requested_amount)],
            "completes_by_deadline": earliest_date <= deadline, "total_paid": requested_amount,
            "start_date": earliest_date, "num_payments": 1, "option_id": None,
        })

    # problem_statement.md: a recommendation is safe only if it completes the full request by
    # desired_completion_date — a late plan is not a safe eligible plan, so it cannot be recommended.
    return [c for c in candidates if c["completes_by_deadline"]]


def rank_candidates(candidates):
    def key(c):
        return (
            0 if c["completes_by_deadline"] else 1,
            0,  # no spending changes at this stage — step 12 handles that layer separately
            c["total_paid"],
            c["start_date"],
            c["num_payments"],
            c["option_id"] or "",
        )
    return sorted(candidates, key=key)


def decide(profile, request, payment_options, current_balance, forecast_events, timeline):
    amount_safe_to_pay, earliest_date, horizon_end = compute_capacity(profile, request, current_balance, timeline)
    candidates = build_candidates(
        profile, request, payment_options, current_balance, forecast_events, timeline,
        amount_safe_to_pay, earliest_date, horizon_end,
    )
    ranked = rank_candidates(candidates)

    if not ranked:
        return {
            "amount_safe_to_pay": amount_safe_to_pay,
            "affordability_status": "not_affordable",
            "recommended_payment_method": "not_recommended",
            "payment_plan": "none",
            "earliest_date_for_full_payment": earliest_date or "",
        }

    best = ranked[0]
    status = {
        "full_payment": "affordable_now",
        "partial_payment": "affordable_with_plan",
        "installments": "affordable_with_plan",
        "wait": "affordable_later",
    }[best["method"]]
    plan_str = "|".join(f"{d}:{_fmt_amount(a)}" for d, a in best["plan"])
    return {
        "amount_safe_to_pay": amount_safe_to_pay,
        "affordability_status": status,
        "recommended_payment_method": best["method"],
        "payment_plan": plan_str,
        "earliest_date_for_full_payment": earliest_date or "",
    }
