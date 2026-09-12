import datetime
import statistics

import conflicts
import currency
import data_loader
import evidence

CASH_STATUSES = {"settled", "pending", "scheduled", "cancelled", "failed", "unrealized"}


def _parse_date(s):
    return datetime.date.fromisoformat(s)


def build_resolved_events(ds, message_facts, image_facts, amount_overrides):
    """Step 9 (part 1): merge blank-amount resolution, evidence-based amendments/cancellations
    (via the coded conflict-resolution hierarchy, no LLM here), currency conversion, and
    linked-event-chain de-duplication into one resolved view of every event."""
    facts_by_event = conflicts.build_facts_by_event(ds, message_facts, image_facts)
    superseded_ids = {e["linked_event_id"] for e in ds.events if e["linked_event_id"]}

    resolved = []
    for event in ds.events:
        if event["event_id"] in superseded_ids:
            continue

        base_amount = event["amount"] if event["amount"] is not None else amount_overrides.get(event["event_id"])
        effective_amount = base_amount
        effective_date = event["settlement_date"]
        effective_status = event["status"]

        facts = facts_by_event.get(event["event_id"], [])
        if len(facts) > 1:
            _, winner = conflicts.resolve_event_state(event, facts)
            if winner.get("action") == "cancel":
                effective_status = "cancelled"
            elif winner.get("action") in ("amend", "delay"):
                if winner.get("new_amount") is not None:
                    effective_amount = winner["new_amount"]
                if winner.get("new_date") is not None:
                    effective_date = winner["new_date"]

        home_currency = ds.profiles[event["user_id"]]["home_currency"]
        unconverted = False
        if effective_amount is not None and event["currency"] != home_currency:
            try:
                effective_amount = currency.convert_to_home_currency(
                    effective_amount, event["currency"], home_currency,
                    event["settlement_date"], ds.exchange_rates,
                )
            except currency.MissingExchangeRateError:
                unconverted = True

        resolved.append({
            "event_id": event["event_id"],
            "user_id": event["user_id"],
            "category": event["category"],
            "event_type": event["event_type"],
            "direction": event["direction"],
            "amount": effective_amount,
            "date": effective_date,
            "status": effective_status,
            "flexibility": event["flexibility"],
            "minimum_allowed_amount": event["minimum_allowed_amount"],
            "unconverted_currency": unconverted,
        })
    return resolved


def detect_recurring_series(events_for_user, as_of_date):
    """Step 9 (part 2): 'detect recurrence only when history supports it'. Groups settled
    history plus any explicitly 'scheduled' (confirmed future) occurrence by category.
    3+ settled occurrences at a consistent gap, OR 2+ occurrences where at least one is an
    explicitly confirmed 'scheduled' instance (e.g. a brand-new employee's one settled
    prorated paycheck plus their one confirmed next payment) at a plausible cadence, is
    'periodic'. 3+ occurrences with irregular gaps (essential variable spend like groceries)
    is 'irregular'. Fewer than that: not enough evidence, no forward projection invented.
    'pending' is deliberately excluded here — it's uncertain, not a confirmed data point."""
    eligible = [
        e for e in events_for_user
        if e["amount"] is not None and (
            (e["status"] == "settled" and e["date"] <= as_of_date) or e["status"] == "scheduled"
        )
    ]
    by_category = {}
    for e in eligible:
        by_category.setdefault(e["category"], []).append(e)

    series = {}
    for category, evs in by_category.items():
        evs.sort(key=lambda e: e["date"])
        has_scheduled_anchor = any(e["status"] == "scheduled" for e in evs)
        min_count = 2 if has_scheduled_anchor else 3
        if len(evs) < min_count:
            series[category] = {"type": "none", "count": len(evs)}
            continue

        dates = [_parse_date(e["date"]) for e in evs]
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        median_gap = statistics.median(gaps)
        last = evs[-1]

        plausible_cadence = 5 <= median_gap <= 45
        consistent = len(gaps) == 1 or all(median_gap * 0.5 <= g <= median_gap * 1.6 for g in gaps)
        if median_gap >= 5 and (consistent if len(evs) >= 3 else plausible_cadence):
            series[category] = {
                "type": "periodic",
                "period_days": round(median_gap),
                "last_date": last["date"],
                "amount": last["amount"],
                "direction": last["direction"],
                "flexibility": last["flexibility"],
                "minimum_allowed_amount": last["minimum_allowed_amount"],
                "count": len(evs),
            }
        else:
            recent = evs[-6:]
            recent_dates = [_parse_date(e["date"]) for e in recent]
            window_days = max((recent_dates[-1] - recent_dates[0]).days, 1)
            avg_per_30d = sum(e["amount"] for e in recent) / window_days * 30
            series[category] = {
                "type": "irregular",
                "avg_per_30d": avg_per_30d,
                "direction": last["direction"],
                "flexibility": last["flexibility"],
                "minimum_allowed_amount": last["minimum_allowed_amount"],
                "count": len(evs),
            }
    return series


def project_forecast_events(request_date, events_for_user, recurring_series, horizon_days=90):
    """Step 10 (part 1): every cash-flow-affecting item expected in [request_date,
    request_date+horizon_days] — explicit confirmed/reserved events plus projected
    recurring ones, never double-counting a cycle already covered by an explicit row."""
    start = _parse_date(request_date)
    end = start + datetime.timedelta(days=horizon_days)
    events_out = []
    covered = []

    for e in events_for_user:
        if e["amount"] is None or e["status"] not in ("pending", "scheduled"):
            continue
        if e["status"] == "pending" and e["direction"] == "credit":
            continue
        e_date = _parse_date(e["date"])
        effective_date = max(e_date, start)
        if effective_date <= end:
            signed = e["amount"] if e["direction"] == "credit" else -e["amount"]
            events_out.append({
                "date": effective_date.isoformat(), "amount": signed, "category": e["category"],
                "event_id": e["event_id"], "source": "explicit",
            })
            covered.append((e["category"], effective_date))

    for category, s in recurring_series.items():
        if s["type"] != "periodic":
            continue
        period = datetime.timedelta(days=s["period_days"])
        next_date = _parse_date(s["last_date"]) + period
        while next_date <= end:
            if next_date >= start and not any(
                c == category and abs((next_date - cd).days) <= 10 for c, cd in covered
            ):
                signed = s["amount"] if s["direction"] == "credit" else -s["amount"]
                events_out.append({
                    "date": next_date.isoformat(), "amount": signed, "category": category,
                    "event_id": None, "source": "projected_periodic",
                })
            next_date += period

    for category, s in recurring_series.items():
        if s["type"] != "irregular":
            continue
        cursor = start
        while cursor <= end:
            if not any(c == category and abs((cursor - cd).days) <= 10 for c, cd in covered):
                signed = s["avg_per_30d"] if s["direction"] == "credit" else -s["avg_per_30d"]
                events_out.append({
                    "date": cursor.isoformat(), "amount": signed, "category": category,
                    "event_id": None, "source": "projected_irregular",
                })
            cursor += datetime.timedelta(days=30)

    events_out.sort(key=lambda x: x["date"])
    return events_out


def simulate_balance(current_balance, forecast_events):
    """Step 10 (part 2): running balance timeline after each projected cash-flow event."""
    timeline = []
    balance = current_balance
    for ev in forecast_events:
        balance += ev["amount"]
        timeline.append({"date": ev["date"], "balance": balance, "event": ev})
    return timeline


def min_balance_up_to(current_balance, timeline, date_str):
    balances = [current_balance] + [t["balance"] for t in timeline if t["date"] <= date_str]
    return min(balances)


def suffix_min_balance(current_balance, timeline, from_date):
    """Min balance from from_date through the end of the timeline (inclusive). Monotonic
    non-decreasing as from_date moves later, which find_earliest_safe_date relies on."""
    events_before = [t for t in timeline if t["date"] < from_date]
    balance_at_start = events_before[-1]["balance"] if events_before else current_balance
    return min([balance_at_start] + [t["balance"] for t in timeline if t["date"] >= from_date])


def find_earliest_safe_date(current_balance, timeline, min_balance_to_keep, amount, request_date, horizon_end):
    """Step 11 helper: earliest date a single lump-sum payment of `amount` stays safe
    through the rest of the 90-day forecast. None if never safe within the horizon."""
    candidates = sorted({request_date, horizon_end} | {t["date"] for t in timeline if request_date <= t["date"] <= horizon_end})
    for d in candidates:
        if suffix_min_balance(current_balance, timeline, d) - amount >= min_balance_to_keep:
            return d
    return None


def schedule_min_balance(current_balance, forecast_events, extra_payments):
    """Min balance over the whole forecast window if extra_payments (list of (date, amount)
    debits) are layered on top of the existing forecast — used to safety-check a candidate
    installment schedule."""
    combined = list(forecast_events) + [
        {"date": d, "amount": -amt, "category": "_candidate_payment", "event_id": None, "source": "candidate"}
        for d, amt in extra_payments
    ]
    combined.sort(key=lambda x: x["date"])
    timeline = simulate_balance(current_balance, combined)
    return min([current_balance] + [t["balance"] for t in timeline])


def build_all(ds, message_facts, image_facts, amount_overrides):
    resolved_events = build_resolved_events(ds, message_facts, image_facts, amount_overrides)
    events_by_user = {}
    for e in resolved_events:
        events_by_user.setdefault(e["user_id"], []).append(e)
    return resolved_events, events_by_user


def _self_check():
    ds = data_loader.load_all()
    amount_overrides = evidence.resolve_blank_amounts(ds)
    image_facts = evidence.extract_all_images(ds)
    message_facts = evidence.extract_all_messages(ds)
    resolved_events, events_by_user = build_all(ds, message_facts, image_facts, amount_overrides)

    assert len(resolved_events) < len(ds.events), "expected some events superseded by linked_event_id chains"
    superseded_removed = len(ds.events) - len(resolved_events)

    req = next(r for r in ds.sample_requests if r["request_id"] == "request_01")
    user = ds.profiles["user_01"]
    series = detect_recurring_series(events_by_user["user_01"], req["request_date"])
    forecast = project_forecast_events(req["request_date"], events_by_user["user_01"], series)
    timeline = simulate_balance(user["current_available_balance"], forecast)

    balance_after_payment = user["current_available_balance"] - 25256
    min_bal = min_balance_up_to(balance_after_payment, timeline, req["desired_completion_date"])
    assert min_bal >= user["minimum_balance_to_keep"], (
        f"sample_requests.csv request_01 says affordable_now paying full 25256, "
        f"but forecast shows min balance {min_bal} < minimum_balance_to_keep {user['minimum_balance_to_keep']}"
    )

    print(
        f"OK: {len(resolved_events)} resolved events ({superseded_removed} superseded by linked chains "
        f"removed), request_01 cross-check against sample_requests.csv passed "
        f"(min balance {min_bal:.2f} >= minimum_balance_to_keep {user['minimum_balance_to_keep']})"
    )


if __name__ == "__main__":
    _self_check()
