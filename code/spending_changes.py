import data_loader
import decision
import evidence
import reconstruct

MAX_CHANGES = 3


def find_flexible_reductions(profile, resolved_events_for_user, recurring_series, forecast_events):
    """Candidates for stop:/reduce_to:, ranked by cash recovered. Only recurring
    (periodic/irregular) categories the user has actually marked flexible AND is willing
    to adjust for THIS category (per financial_profiles.csv), never a protected category."""
    protect = set(profile["expense_categories_to_protect"])
    can_reduce = set(profile["expense_categories_user_is_willing_to_reduce"])
    can_stop = set(profile["expense_categories_user_is_willing_to_stop"])

    by_date = sorted(resolved_events_for_user, key=lambda e: e["date"])
    candidates = []
    for category, s in recurring_series.items():
        if s["type"] not in ("periodic", "irregular") or category in protect:
            continue
        flexibility = s.get("flexibility")
        if flexibility not in ("stoppable", "reducible", "reducible_or_stoppable"):
            continue
        occurrences = [f for f in forecast_events if f["category"] == category and f["amount"] < 0]
        if not occurrences:
            continue
        rep = next((e for e in reversed(by_date) if e["category"] == category), None)
        if rep is None:
            continue

        if flexibility in ("stoppable", "reducible_or_stoppable") and category in can_stop:
            recover = sum(-f["amount"] for f in occurrences)
            candidates.append({
                "action": "stop", "event_id": rep["event_id"], "category": category, "recover": recover,
            })

        if flexibility in ("reducible", "reducible_or_stoppable") and category in can_reduce:
            min_amt = s.get("minimum_allowed_amount")
            per_occurrence = s.get("amount") if s["type"] == "periodic" else s.get("avg_per_30d")
            if min_amt is not None and per_occurrence is not None and per_occurrence > min_amt:
                recover = (per_occurrence - min_amt) * len(occurrences)
                candidates.append({
                    "action": "reduce_to", "event_id": rep["event_id"], "category": category,
                    "new_amount": min_amt, "recover": recover,
                })

    candidates.sort(key=lambda c: -c["recover"])
    # stop and reduce_to are mutually exclusive on the same event per problem_statement.md —
    # keep only the higher-recovery action per category
    seen_categories = set()
    deduped = []
    for c in candidates:
        if c["category"] in seen_categories:
            continue
        seen_categories.add(c["category"])
        deduped.append(c)
    return deduped


def _apply_reductions(forecast_events, reductions):
    stop_categories = {r["category"] for r in reductions if r["action"] == "stop"}
    reduce_map = {r["category"]: r["new_amount"] for r in reductions if r["action"] == "reduce_to"}
    out = []
    for ev in forecast_events:
        if ev["category"] in stop_categories:
            continue
        if ev["category"] in reduce_map and ev["amount"] < 0:
            out.append({**ev, "amount": -reduce_map[ev["category"]]})
        else:
            out.append(ev)
    return out


def try_with_spending_changes(profile, request, payment_options, current_balance,
                               user_events, recurring_series, forecast_events, baseline_result):
    """Step 12. Only engages when the baseline (no-changes) recommendation is wait/not_recommended
    — an affordable_now/affordable_with_plan baseline already satisfies ranking rule 2 (no changes)
    by construction. amount_safe_to_pay / earliest_date_for_full_payment are NEVER altered here —
    both are explicitly defined as pre-spending-change values; only the recommendation/plan can
    change. Tries the fewest possible changes (1, then 2, then 3) before giving up."""
    if baseline_result["recommended_payment_method"] not in ("wait", "not_recommended"):
        return baseline_result, "none"

    reductions = find_flexible_reductions(profile, user_events, recurring_series, forecast_events)
    if not reductions:
        return baseline_result, "none"

    request_date = request["request_date"]
    requested_amount = request["requested_amount"]
    min_bal = profile["minimum_balance_to_keep"]

    for n in range(1, min(MAX_CHANGES, len(reductions)) + 1):
        chosen = reductions[:n]
        modified_forecast = _apply_reductions(forecast_events, chosen)
        modified_timeline = reconstruct.simulate_balance(current_balance, modified_forecast)

        if reconstruct.suffix_min_balance(current_balance, modified_timeline, request_date) - requested_amount >= min_bal:
            plan_str = f"{request_date}:{decision._fmt_amount(requested_amount)}"
            changes_str = "|".join(
                f"stop:{c['event_id']}" if c["action"] == "stop"
                else f"reduce_to:{c['event_id']}:{decision._fmt_amount(c['new_amount'])}"
                for c in chosen
            )
            return {
                **baseline_result,
                "affordability_status": "affordable_with_plan",
                "recommended_payment_method": "full_payment",
                "payment_plan": plan_str,
            }, changes_str

        if "installments" in set(profile["payment_methods_user_will_consider"]) and profile["max_installment_months"] is not None:
            for opt in payment_options:
                if opt["payment_method"] != "installments" or opt["number_of_payments"] > profile["max_installment_months"]:
                    continue
                plan = decision._build_installment_plan(opt)
                if reconstruct.schedule_min_balance(current_balance, modified_forecast, plan) >= min_bal:
                    plan_str = "|".join(f"{d}:{decision._fmt_amount(a)}" for d, a in plan)
                    changes_str = "|".join(
                        f"stop:{c['event_id']}" if c["action"] == "stop"
                        else f"reduce_to:{c['event_id']}:{decision._fmt_amount(c['new_amount'])}"
                        for c in chosen
                    )
                    return {
                        **baseline_result,
                        "affordability_status": "affordable_with_plan",
                        "recommended_payment_method": "installments",
                        "payment_plan": plan_str,
                    }, changes_str

    return baseline_result, "none"


def _self_check():
    ds = data_loader.load_all()
    amount_overrides = evidence.resolve_blank_amounts(ds)
    image_facts = evidence.extract_all_images(ds)
    message_facts = evidence.extract_all_messages(ds)
    resolved_events, events_by_user = reconstruct.build_all(ds, message_facts, image_facts, amount_overrides)

    upgraded = 0
    unchanged = 0
    for req in ds.requests:
        profile = ds.profiles[req["user_id"]]
        user_events = events_by_user.get(req["user_id"], [])
        series = reconstruct.detect_recurring_series(user_events, req["request_date"])
        forecast = reconstruct.project_forecast_events(req["request_date"], user_events, series)
        timeline = reconstruct.simulate_balance(profile["current_available_balance"], forecast)
        options = ds.payment_options_by_request.get(req["request_id"], [])
        baseline = decision.decide(profile, req, options, profile["current_available_balance"], forecast, timeline)
        result, changes = try_with_spending_changes(
            profile, req, options, profile["current_available_balance"], user_events, series, forecast, baseline
        )
        if changes != "none":
            upgraded += 1
            assert result["affordability_status"] in ("affordable_now", "affordable_with_plan")
            assert changes.count("|") + 1 <= MAX_CHANGES
        else:
            unchanged += 1

    print(f"OK: {upgraded} requests upgraded via spending changes, {unchanged} unchanged (250 total)")


if __name__ == "__main__":
    _self_check()
