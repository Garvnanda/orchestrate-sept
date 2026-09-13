"""Running-balance primitives used by the decision engine. Pure functions, no I/O."""
import datetime


def parse_date(s):
    return datetime.date.fromisoformat(s)


def simulate_balance(current_balance, forecast_events):
    """Running balance after each forecast event, in the given (already intraday-ordered) sequence."""
    timeline = []
    balance = current_balance
    for ev in forecast_events:
        balance += ev["amount"]
        timeline.append({"date": ev["date"], "balance": balance, "event": ev})
    return timeline


def baseline_min_balance(current_balance, timeline):
    return min([current_balance] + [t["balance"] for t in timeline])


def suffix_min_balance(current_balance, timeline, from_date):
    """Lowest balance a payment made on from_date would see: the balance after all of that day's cash
    flows (a payment made on a payday is made after the salary lands), then every later point."""
    through = [t for t in timeline if t["date"] <= from_date]
    after_day = through[-1]["balance"] if through else current_balance
    return min([after_day] + [t["balance"] for t in timeline if t["date"] > from_date])


def find_earliest_safe_date(current_balance, timeline, min_balance_to_keep, amount, request_date, horizon_end):
    """Earliest date a single payment of `amount` keeps the whole forecast at or above the minimum.
    None if the forecast breaches the minimum even without paying, or no date in the horizon works."""
    if baseline_min_balance(current_balance, timeline) < min_balance_to_keep:
        return None
    candidates = sorted({request_date} | {t["date"] for t in timeline if request_date <= t["date"] <= horizon_end})
    for d in candidates:
        if suffix_min_balance(current_balance, timeline, d) - amount >= min_balance_to_keep:
            return d
    return None


def schedule_min_balance(current_balance, forecast_events, extra_payments):
    """Minimum balance if extra_payments [(date, amount)] are paid on top of the forecast. A stable sort
    by date keeps each payment after that day's forecast cash flows."""
    combined = list(forecast_events) + [
        {"date": d, "amount": -amt, "category": "_candidate_payment", "event_id": None, "source": "candidate"}
        for d, amt in extra_payments
    ]
    combined.sort(key=lambda x: x["date"])
    return baseline_min_balance(current_balance, simulate_balance(current_balance, combined))


if __name__ == "__main__":
    events = [
        {"date": "2026-07-10", "amount": -300.0},
        {"date": "2026-07-15", "amount": -100.0},   # expense on payday lands before the salary
        {"date": "2026-07-15", "amount": 2000.0},
        {"date": "2026-08-01", "amount": -900.0},
    ]
    tl = simulate_balance(1000.0, events)
    assert baseline_min_balance(1000.0, tl) == 600.0
    assert suffix_min_balance(1000.0, tl, "2026-07-01") == 600.0
    assert suffix_min_balance(1000.0, tl, "2026-07-15") == 1700.0          # salary counted for a payday payment
    assert find_earliest_safe_date(1000.0, tl, 500.0, 1000.0, "2026-07-01", "2026-09-29") == "2026-07-15"
    assert find_earliest_safe_date(1000.0, tl, 700.0, 10.0, "2026-07-01", "2026-09-29") is None  # baseline breach
    assert schedule_min_balance(1000.0, events, [("2026-07-15", 1000.0)]) == 600.0
    assert schedule_min_balance(1000.0, events, [("2026-07-10", 500.0)]) == 100.0
    print("OK: balance primitives (payday ordering, baseline breach, schedule layering)")
