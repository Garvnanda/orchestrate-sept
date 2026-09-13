"""90-day cash-flow forecast.

Income and expenses are modeled as streams, not raw categories:
- Regular employer pay is a monthly stream on its usual pay day. Bonuses, commissions, arrears, gig
  payouts, freelance invoices, prizes and reimbursements are never projected unless a message confirms a
  specific amount and date (problem_statement.md: do not invent unsupported income).
- A stream whose latest pay is described as final, or that a message says ended, stops.
- Recurring expenses are learned only from settled history with descriptions that recur across the dataset;
  rare descriptions (authorizations, invoices, duplicate charges, one-off purchases) never set a cadence.
- Pending and scheduled debits are reserved once on their date; pending credits never count.
- Message scenarios (see scenarios.py) amend the streams with deterministic rules.
Every tunable arithmetic choice lives in DEFAULTS so it can be calibrated against sample_requests.csv.
"""
import calendar
import datetime
import math
import re
import statistics
from collections import Counter, defaultdict

import currency

# Calibrated on dataset/sample_requests.csv with code/evaluate_samples.py (see technical.md for the sweep).
DEFAULTS = {
    "horizon_days": 90,
    "include_start_day": True,
    "amount_estimator": "median",
    "rounding": "none",
    "fixed_if_constant": True,
    "count_second_household_income": False,
    "count_recurring_side_income": True,
    "variable_spend_from_start": False,
    "count_arrears": True,
    "rare_description_threshold": 20,
}

IRREGULAR_INCOME = re.compile(
    r"bonus|commission|arrears|payout|earnings|marketplace|invoice|project|contract payment|milestone|"
    r"retainer|consulting|independent|reimbursement|prize|proceeds|seasonal|season|temporary assignment|refund|reversal",
    re.I,
)
SECOND_INCOME = re.compile(r"second household", re.I)
TERMINAL_PAY = re.compile(r"\bfinal\b", re.I)
NET_SALARY_DOC = re.compile(r"\b(19|20)\d\d\b|net salary", re.I)


def _d(s):
    return datetime.date.fromisoformat(s)


def _add_months(day, months, pay_day=None):
    m = day.month - 1 + months
    y, m = day.year + m // 12, m % 12 + 1
    target = pay_day or day.day
    return datetime.date(y, m, min(target, calendar.monthrange(y, m)[1]))


def _estimate(points, cfg, request_date):
    """points: [(date, amount)] oldest first. Returns the per-occurrence amount to project."""
    amounts = [a for _, a in points]
    if cfg["fixed_if_constant"] and len(set(amounts)) == 1:
        return amounts[0]
    name = cfg["amount_estimator"]
    if name.startswith("window"):
        days = int(name[len("window"):])
        cutoff = _d(request_date) - datetime.timedelta(days=days)
        recent = [a for d, a in points if _d(d) > cutoff] or amounts[-1:]
        est = statistics.mean(recent)
    else:
        est = {
            "last": lambda a: a[-1],
            "mean": statistics.mean,
            "median": statistics.median,
            "max": max,
            "mean3": lambda a: statistics.mean(a[-3:]),
            "mean4": lambda a: statistics.mean(a[-4:]),
            "mean6": lambda a: statistics.mean(a[-6:]),
            "median6": lambda a: statistics.median(a[-6:]),
        }[name](amounts)
    return {
        "none": lambda x: round(x, 2),
        "round": round,
        "ceil": math.ceil,
        "floor": math.floor,
    }[cfg["rounding"]](est)


def description_frequency(ds):
    return Counter(e["description"] for e in ds.events)


def _to_home(ds, amount, from_ccy, home_ccy, on_date):
    if from_ccy == home_ccy or amount is None:
        return amount
    try:
        return currency.convert_to_home_currency(amount, from_ccy, home_ccy, on_date, ds.exchange_rates)
    except currency.MissingExchangeRateError:
        earlier = sorted(k for k in ds.exchange_rates if k[1] == from_ccy and k[2] == home_ccy and k[0] <= on_date)
        if not earlier:
            raise
        return amount * ds.exchange_rates[earlier[-1]]


def _pay_day(dates):
    return Counter(d.day for d in dates).most_common(1)[0][0]


def build_income(ds, user_events, request_date, facts, horizon_end, cfg):
    """Projected credits in the window: [(date, amount, label)]."""
    home = ds.profiles[user_events[0]["user_id"]]["home_currency"] if user_events else None
    start = _d(request_date)
    payroll = sorted(
        (e for e in user_events
         if e["category"] == "salary" and e["direction"] == "credit" and e["amount"] is not None
         and e["status"] in ("settled", "scheduled")
         and not IRREGULAR_INCOME.search(e["description"]) and not SECOND_INCOME.search(e["description"])
         and not NET_SALARY_DOC.search(e["description"])),
        key=lambda e: e["date"],
    )
    credits = []
    ended = False
    amount = None
    pay_day = None
    next_date = None

    history = [e for e in payroll if e["status"] == "settled" and e["date"] <= request_date]
    scheduled = [e for e in payroll if e["status"] == "scheduled"]
    if history:
        pay_day = _pay_day([_d(e["date"]) for e in history[-6:]])
        last = history[-1]
        recent = [_to_home(ds, e["amount"], e["currency"], home, e["date"]) for e in history[-6:]]
        counts = Counter(recent)
        top = max(counts.values())
        amount = next(a for a in reversed(recent) if counts[a] == top)  # usual pay, not a one-off reduced payslip
        ended = bool(TERMINAL_PAY.search(last["description"]))
        next_date = _add_months(_d(last["date"]), 1, pay_day)
    for e in scheduled:
        credits.append((_d(e["date"]), _to_home(ds, e["amount"], e["currency"], home, e["date"]), "scheduled salary"))
        amount = _to_home(ds, e["amount"], e["currency"], home, e["date"])
        pay_day = pay_day or _d(e["date"]).day
        next_date = _add_months(_d(e["date"]), 1, pay_day)
        ended = False

    overrides = {}          # date -> amount for specific paydays
    amount_from = []        # (effective_date, amount) permanent changes
    temporary = None        # (amount, cycles)
    moved_to = None
    one_offs = []
    for f in facts:
        s = f["scenario"]
        eff = _d(f["effective_date"]) if f.get("effective_date") else None
        amt = f.get("amount")
        if amt is not None and f.get("currency") and home and f["currency"] != home:
            try:
                amt = _to_home(ds, amt, f["currency"], home, (eff or start).isoformat())
            except currency.MissingExchangeRateError:
                amt = None
        if s == "income_ended":
            ended = True
        elif s in ("salary_amount_change", "remaining_household_income") and amt:
            amount_from.append((eff or start, amt))
        elif s == "salary_temporary_change" and amt:
            temporary = (amt, f.get("cycles") or 1)
        elif s == "salary_date_change" and eff:
            moved_to = eff
        elif s in ("salary_resumes", "first_salary_confirmed", "salary_confirmed_foreign_currency") and amt and eff:
            ended = False
            next_date = eff
            pay_day = eff.day
            amount = amt
            credits = [c for c in credits if c[0] < eff]
        elif s == "salary_with_one_time_arrears" and amt:
            amount_from.append((start, amt))
            if cfg["count_arrears"] and f.get("secondary_amount"):
                one_offs.append(("next_payday", f["secondary_amount"]))
        elif s == "invoice_payment_confirmed" and amt and eff:
            credits.append((eff, amt, "confirmed invoice"))

    if not ended and amount is not None and next_date is not None:
        scheduled_dates = {c[0] for c in credits}
        d = next_date
        cycle = 0
        while d <= horizon_end:
            pay = d
            if moved_to and cycle == 0 and not scheduled_dates:
                pay = moved_to
            value = amount
            for eff, amt in amount_from:
                if pay >= eff:
                    value = amt
            if temporary and cycle < temporary[1]:
                value = temporary[0]
            if pay >= start and pay not in scheduled_dates:
                credits.append((pay, value, "projected salary"))
            cycle += 1
            d = _add_months(next_date, cycle, pay_day)
        if one_offs and credits:
            first = min(c[0] for c in credits if c[0] >= start)
            for _, amt in one_offs:
                credits.append((first, amt, "one-time arrears"))

    if cfg["count_recurring_side_income"]:
        side = sorted((e for e in user_events if e["category"] == "salary" and e["direction"] == "credit"
                       and e["status"] == "settled" and e["date"] <= request_date and e["amount"] is not None
                       and re.search(r"project|contract payment|milestone|retainer|consulting|independent", e["description"], re.I)),
                      key=lambda e: e["date"])
        if len(side) >= 4:
            dates = [_d(e["date"]) for e in side]
            span = max((dates[-1] - dates[0]).days, 1)
            per_day = sum(e["amount"] for e in side[:-1]) / span
            gap = max(round(span / (len(side) - 1)), 1)
            amt = min(e["amount"] for e in side[-6:])
            d = dates[-1] + datetime.timedelta(days=gap)
            while d <= horizon_end:
                if d >= start:
                    credits.append((d, amt, "recurring side income"))
                d += datetime.timedelta(days=gap)

    if cfg["count_second_household_income"]:
        second = sorted((e for e in user_events if SECOND_INCOME.search(e["description"]) and e["status"] == "settled"
                         and e["date"] <= request_date and e["amount"] is not None), key=lambda e: e["date"])
        if len(second) >= 3:
            amt = _estimate([(e["date"], e["amount"]) for e in second], cfg, request_date)
            day = _pay_day([_d(e["date"]) for e in second])
            d = _add_months(_d(second[-1]["date"]), 1, day)
            while d <= horizon_end:
                if d >= start:
                    credits.append((d, amt, "second household income"))
                d = _add_months(d, 1, day)
    return [c for c in credits if start <= c[0] <= horizon_end]


def build_expenses(ds, user_events, request_date, facts, horizon_end, cfg, freq):
    """Projected and reserved debits in the window: [(date, amount, category, event_id, source)]."""
    home = ds.profiles[user_events[0]["user_id"]]["home_currency"] if user_events else None
    start = _d(request_date)
    out = []

    for e in user_events:
        if e["direction"] != "debit" or e["amount"] is None:
            continue
        if e["status"] in ("pending", "scheduled"):
            when = max(_d(e["date"]), start)
            if when <= horizon_end:
                out.append((when, _to_home(ds, e["amount"], e["currency"], home, e["date"]), e["category"], e["event_id"], "reserved"))

    all_settled = defaultdict(list)
    for e in user_events:
        if e["direction"] == "debit" and e["status"] == "settled" and e["date"] <= request_date:
            all_settled[e["category"]].append(e)
    recurring = defaultdict(list)
    for e in user_events:
        if (e["direction"] == "debit" and e["status"] == "settled" and e["amount"] is not None
                and e["date"] <= request_date and freq[e["description"]] >= cfg["rare_description_threshold"]
                and e["event_type"] in ("expense", "subscription", "debt_payment")):
            recurring[e["category"]].append(e)

    percent_changes = {f["category"]: f["percent"] for f in facts
                       if f["scenario"] == "expense_percent_change" and f.get("percent") and f.get("category")}
    reserved_categories = defaultdict(list)
    for when, _, cat, _, src in out:
        reserved_categories[cat].append(when)

    series = {}
    for category, evs in recurring.items():
        evs.sort(key=lambda e: e["date"])
        if len(evs) < 3:
            continue
        dates = [_d(e["date"]) for e in evs]
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        gap = statistics.median(gaps)
        last_any = max([_d(x["date"]) for x in all_settled.get(category, [])] + [dates[-1]])
        points = [(e["date"], _to_home(ds, e["amount"], e["currency"], home, e["date"])) for e in evs]
        value = _estimate(points, cfg, request_date)
        monthly = 26 <= gap <= 33
        series[category] = {"monthly": monthly, "gap": round(gap), "last": dates[-1], "amount": value,
                            "pay_day": _pay_day(dates[-6:]) if monthly else None, "event": evs[-1]}
        k = 1
        pct_applied = False
        anchor = last_any
        if cfg["variable_spend_from_start"] and not monthly:
            anchor = start - datetime.timedelta(days=round(gap))
        while True:
            d = _add_months(anchor, k, series[category]["pay_day"]) if monthly else anchor + datetime.timedelta(days=round(gap) * k)
            if d > horizon_end:
                break
            if d > start or (cfg["include_start_day"] and d == start):
                if any(abs((d - r).days) <= 3 for r in reserved_categories.get(category, [])):
                    k += 1
                    continue
                amt = value
                if category in percent_changes:
                    amt = round(value * (1 + percent_changes[category] / 100.0), 2)
                    pct_applied = True
                out.append((d, amt, category, None, "projected"))
            k += 1

    events_by_id = {e["event_id"]: e for e in user_events}
    for f in facts:
        if f["scenario"] == "failed_debit_will_retry" and f.get("related_event_id") in events_by_id:
            failed = events_by_id[f["related_event_id"]]
            if failed["status"] == "failed" and failed["amount"] is not None:
                retry_on = max(_d(failed["date"]), start)
                out.append((retry_on, _to_home(ds, failed["amount"], failed["currency"], home, failed["date"]),
                            failed["category"], failed["event_id"], "message: failed debit will be retried"))
        if f["scenario"] == "new_recurring_expense" and f.get("amount") and f.get("effective_date"):
            d = _d(f["effective_date"])
            while d <= horizon_end:
                if d >= start:
                    out.append((d, f["amount"], f.get("category") or "new_expense", None, "message: new recurring expense"))
                d = _add_months(d, 1)
    return [x for x in out if start <= x[0] <= horizon_end], series


def prepare_events(ds, blank_amounts):
    """user_id -> event dicts in original currency. Blank amounts come from the linked image; an event
    superseded by a later row in its linked_event_id chain is dropped so a transaction counts once."""
    superseded = {e["linked_event_id"] for e in ds.events if e["linked_event_id"]}
    by_user = defaultdict(list)
    for e in ds.events:
        if e["event_id"] in superseded:
            continue
        amount = e["amount"] if e["amount"] is not None else blank_amounts.get(e["event_id"])
        by_user[e["user_id"]].append({
            "event_id": e["event_id"], "user_id": e["user_id"], "category": e["category"],
            "description": e["description"], "event_type": e["event_type"], "direction": e["direction"],
            "amount": amount, "currency": e["currency"], "date": e["settlement_date"] or e["event_date"],
            "status": e["status"], "flexibility": e["flexibility"],
            "minimum_allowed_amount": e["minimum_allowed_amount"],
        })
    return by_user


def facts_for(ds, scenario_results, user_id, request_date):
    """Scenario facts from this user's messages sent on or before request_date, oldest first."""
    msgs = sorted((m for m in ds.messages if m["user_id"] == user_id and m["sent_at"][:10] <= request_date),
                  key=lambda m: m["sent_at"])
    facts = []
    for m in msgs:
        for f in scenario_results.get(m["message_id"], {}).get("facts", []):
            facts.append({**f, "message_id": m["message_id"], "related_event_id": m["related_event_id"] or None})
    return facts


def build_forecast(ds, user_events, request, facts, freq, cfg=None):
    """Returns forecast events in the shape decision.py consumes, ordered so that on any one day expenses
    land before income (the conservative intraday order)."""
    cfg = {**DEFAULTS, **(cfg or {})}
    start = _d(request["request_date"])
    horizon_end = start + datetime.timedelta(days=cfg["horizon_days"])
    credits = build_income(ds, user_events, request["request_date"], facts, horizon_end, cfg)
    debits, series = build_expenses(ds, user_events, request["request_date"], facts, horizon_end, cfg, freq)
    events = [{"date": d.isoformat(), "amount": -a, "category": c, "event_id": eid, "source": src, "order": 0}
              for d, a, c, eid, src in debits]
    events += [{"date": d.isoformat(), "amount": a, "category": "salary", "event_id": None, "source": label, "order": 1}
               for d, a, label in credits]
    events.sort(key=lambda e: (e["date"], e["order"]))
    return events, series
