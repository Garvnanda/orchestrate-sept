"""Score the decision engine against dataset/sample_requests.csv (25 labeled rows).

sample_requests.csv is never used in any prompt, so this is an independent check of the pipeline. It is
not a held-out test: forecast rules were calibrated against these rows, so the numbers are in-sample
agreement, not a generalization estimate. Run: python code/evaluate_samples.py [-v]
"""
import sys

import data_loader
import decision
import explanation
import main

FIELDS = [
    "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation",
]


def _norm_plan(plan):
    if plan in ("", "none"):
        return plan
    return "|".join(f"{d}:{round(float(a), 2)}" for d, a in (p.split(":") for p in plan.split("|")))


def _match(field, expected, got):
    if field == "amount_safe_to_pay":
        return abs(float(expected) - float(got)) <= 0.01
    if field == "payment_plan":
        return _norm_plan(expected) == _norm_plan(got)
    return expected == got


def evaluate(cfg=None, ds=None, ctx=None):
    ds = ds or data_loader.load_all()
    ctx = ctx or main.build_context(ds)
    hits = {f: 0 for f in FIELDS}
    rows = []
    for req in ds.sample_requests:
        try:
            d = main.decide_request(ds, req, ctx, cfg)
            got = {**d["result"], "spending_changes_needed": d["changes"]}
            got["decision_explanation"] = explanation.explain(req, d["profile"], d["result"], d["chosen"])
        except Exception as e:
            got = {f: f"ERROR {type(e).__name__}: {e}" for f in FIELDS}
            got["amount_safe_to_pay"] = "-1"
        got["amount_safe_to_pay"] = decision._fmt_amount(float(got["amount_safe_to_pay"]))
        misses = []
        for f in FIELDS:
            if _match(f, req[f], got[f]):
                hits[f] += 1
            else:
                misses.append((f, req[f], got[f]))
        rows.append((req["request_id"], misses))
    return len(ds.sample_requests), hits, rows


if __name__ == "__main__":
    total, hits, rows = evaluate()
    for f in FIELDS:
        print(f"{f:32s} {hits[f]:2d}/{total}")
    exact = sum(1 for _, m in rows if not [x for x in m if x[0] != "decision_explanation"])
    print(f"{'all decision fields exact':32s} {exact:2d}/{total}")
    if "-v" in sys.argv:
        for rid, misses in rows:
            for f, exp, got in misses:
                print(f"  {rid} {f}: expected={exp!r} got={got!r}")
