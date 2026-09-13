"""decision_explanation: deterministic, grounded sentences built only from computed fields.

Style follows the explanations in dataset/sample_requests.csv (short, imperative, amounts with currency
and thousands separators, dates as "8 August 2025"). No LLM is involved, so every number in the text is
exactly a number the decision engine produced.
"""
import datetime


def money(currency, amount):
    rounded = round(float(amount), 2)
    text = f"{rounded:,.0f}" if rounded == int(rounded) else f"{rounded:,.2f}"
    return f"{currency} {text}"


def long_date(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B')} {d.year}"


def _plan(payment_plan):
    return [(d, float(a)) for d, a in (p.split(":") for p in payment_plan.split("|"))] if payment_plan != "none" else []


def _changes_clause(chosen, currency):
    parts = []
    for c in sorted(chosen, key=lambda c: (c["action"] != "stop", c["event_id"])):
        name = (c.get("description") or c["category"]).strip().lower()
        if c["action"] == "stop":
            parts.append(f"stop the {name}")
        else:
            parts.append(f"reduce the {name} to {money(currency, c['new_amount'])}")
    clause = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return clause[0].upper() + clause[1:]


def explain(request, profile, result, chosen):
    ccy = profile["home_currency"]
    minimum = money(ccy, profile["minimum_balance_to_keep"])
    requested = money(ccy, request["requested_amount"])
    method = result["recommended_payment_method"]
    status = result["affordability_status"]
    plan = _plan(result["payment_plan"])
    safe = float(result["amount_safe_to_pay"])

    if method == "not_recommended":
        accepted = set(profile["payment_methods_user_will_consider"])
        if request["allows_partial_payment"] and "partial_payment" in accepted and 0 < safe < request["requested_amount"]:
            return (f"Do not proceed with the {requested} request. Although {money(ccy, safe)} is available today, "
                    f"the full amount cannot be completed safely within 90 days.")
        return (f"Do not make this payment by {long_date(request['desired_completion_date'])}. "
                f"None of the available options keeps the {minimum} minimum protected.")

    if method == "wait":
        return (f"Pay {requested} in full on {long_date(plan[0][0])}. "
                f"Paying earlier would take the balance below the {minimum} minimum.")

    if method == "partial_payment":
        (d1, a1), (d2, a2) = plan
        return (f"Pay {money(ccy, a1)} today and the remaining {money(ccy, a2)} on {long_date(d2)}. "
                f"This completes the full request and keeps the {minimum} minimum protected.")

    if method == "installments":
        action = f"use {len(plan)} installments of {money(ccy, plan[0][1])}, starting {long_date(plan[0][0])}"
    else:
        action = f"pay {requested} today"

    if chosen:
        return f"{_changes_clause(chosen, ccy)}, then {action}. This leaves at least {minimum} available."
    if status == "affordable_now":
        return f"Pay {requested} today. This leaves at least {minimum} available over the next 90 days."
    return f"{action[0].upper() + action[1:]}. This leaves at least {minimum} available."


if __name__ == "__main__":
    profile = {"home_currency": "IDR", "minimum_balance_to_keep": 29158400.0,
               "payment_methods_user_will_consider": ["partial_payment", "installments"]}
    request = {"requested_amount": 46018000.0, "desired_completion_date": "2025-10-10", "allows_partial_payment": False}
    result = {"recommended_payment_method": "installments", "affordability_status": "affordable_with_plan",
              "payment_plan": "2025-08-08:15952906.67|2025-09-07:15952906.67|2025-10-07:15952906.67",
              "amount_safe_to_pay": 17229139.2}
    got = explain(request, profile, result, [])
    expected = "Use 3 installments of IDR 15,952,906.67, starting 8 August 2025. This leaves at least IDR 29,158,400 available."
    assert got == expected, got
    chosen = [{"action": "reduce_to", "event_id": "event_1816", "category": "streaming", "new_amount": 23.5,
               "description": "Streaming subscription"},
              {"action": "stop", "event_id": "event_1815", "category": "cloud_storage", "description": "Online backup subscription"}]
    got = explain({"requested_amount": 1574.4, "desired_completion_date": "2026-04-14", "allows_partial_payment": False},
                  {"home_currency": "USD", "minimum_balance_to_keep": 1800.0, "payment_methods_user_will_consider": ["full_payment"]},
                  {"recommended_payment_method": "full_payment", "affordability_status": "affordable_with_plan",
                   "payment_plan": "2026-04-03:1574.40", "amount_safe_to_pay": 1543.35}, chosen)
    expected = ("Stop the online backup subscription and reduce the streaming subscription to USD 23.50, "
                "then pay USD 1,574.40 today. This leaves at least USD 1,800 available.")
    assert got == expected, got
    print("OK: explanation templates reproduce sample_requests.csv wording for request_02 and request_21")
