import csv
import os
from dataclasses import dataclass


def _read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _split_pipe(value):
    return value.split("|") if value else []


def _float_or_none(value):
    return float(value) if value not in (None, "") else None


def _int_or_none(value):
    return int(value) if value not in (None, "") else None


@dataclass
class Dataset:
    profiles: dict
    events: list
    events_by_id: dict
    events_by_user: dict
    exchange_rates: dict
    requests: list
    requests_by_id: dict
    payment_options_by_request: dict
    messages: list
    messages_by_request: dict
    messages_by_event: dict
    images: list
    images_by_event: dict
    images_by_request: dict
    sample_requests: list


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_DIR = os.path.join(REPO_ROOT, "dataset")


def load_all(dataset_dir=DATASET_DIR):
    def path(name):
        return os.path.join(dataset_dir, name)

    profiles = {}
    for row in _read_rows(path("financial_profiles.csv")):
        row["current_available_balance"] = _float_or_none(row["current_available_balance"])
        row["minimum_balance_to_keep"] = _float_or_none(row["minimum_balance_to_keep"])
        row["financial_priorities"] = _split_pipe(row["financial_priorities"])
        row["expense_categories_to_protect"] = _split_pipe(row["expense_categories_to_protect"])
        row["expense_categories_user_is_willing_to_reduce"] = _split_pipe(row["expense_categories_user_is_willing_to_reduce"])
        row["expense_categories_user_is_willing_to_stop"] = _split_pipe(row["expense_categories_user_is_willing_to_stop"])
        row["payment_methods_user_will_consider"] = _split_pipe(row["payment_methods_user_will_consider"])
        row["max_installment_months"] = _int_or_none(row["max_installment_months"])
        profiles[row["user_id"]] = row

    events = _read_rows(path("financial_events.csv"))
    events_by_id = {}
    events_by_user = {}
    for row in events:
        row["amount"] = _float_or_none(row["amount"])
        row["minimum_allowed_amount"] = _float_or_none(row["minimum_allowed_amount"])
        events_by_id[row["event_id"]] = row
        events_by_user.setdefault(row["user_id"], []).append(row)

    exchange_rates = {}
    for row in _read_rows(path("exchange_rates.csv")):
        key = (row["rate_date"], row["from_currency"], row["to_currency"])
        exchange_rates[key] = float(row["rate"])

    requests = _read_rows(path("requests.csv"))
    requests_by_id = {}
    for row in requests:
        row["requested_amount"] = _float_or_none(row["requested_amount"])
        row["allows_partial_payment"] = row["allows_partial_payment"].strip().lower() == "true"
        requests_by_id[row["request_id"]] = row

    payment_options_by_request = {}
    for row in _read_rows(path("request_payment_options.csv")):
        row["payment_amount"] = _float_or_none(row["payment_amount"])
        row["number_of_payments"] = _int_or_none(row["number_of_payments"])
        row["payment_frequency_days"] = _int_or_none(row["payment_frequency_days"])
        row["financing_fee"] = _float_or_none(row["financing_fee"])
        row["total_payable_amount"] = _float_or_none(row["total_payable_amount"])
        payment_options_by_request.setdefault(row["request_id"], []).append(row)

    messages = _read_rows(path("messages.csv"))
    messages_by_request = {}
    messages_by_event = {}
    for row in messages:
        if row["request_id"]:
            messages_by_request.setdefault(row["request_id"], []).append(row)
        if row["related_event_id"]:
            messages_by_event.setdefault(row["related_event_id"], []).append(row)

    images = _read_rows(path("images.csv"))
    images_by_event = {}
    images_by_request = {}
    for row in images:
        if row["related_event_id"]:
            images_by_event.setdefault(row["related_event_id"], []).append(row)
        if row["request_id"]:
            images_by_request.setdefault(row["request_id"], []).append(row)

    sample_requests = _read_rows(path("sample_requests.csv"))
    for row in sample_requests:
        row["requested_amount"] = _float_or_none(row["requested_amount"])
        row["allows_partial_payment"] = row["allows_partial_payment"].strip().lower() == "true"

    return Dataset(
        profiles=profiles,
        events=events,
        events_by_id=events_by_id,
        events_by_user=events_by_user,
        exchange_rates=exchange_rates,
        requests=requests,
        requests_by_id=requests_by_id,
        payment_options_by_request=payment_options_by_request,
        messages=messages,
        messages_by_request=messages_by_request,
        messages_by_event=messages_by_event,
        images=images,
        images_by_event=images_by_event,
        images_by_request=images_by_request,
        sample_requests=sample_requests,
    )


def _self_check():
    ds = load_all()
    assert len(ds.requests) == 250, f"expected 250 requests, got {len(ds.requests)}"

    for req in ds.requests:
        assert req["user_id"] in ds.profiles, f"{req['request_id']} references unknown user {req['user_id']}"
        assert req["requested_amount"] is not None and req["requested_amount"] > 0
        opts = ds.payment_options_by_request.get(req["request_id"], [])
        assert 2 <= len(opts) <= 4, f"{req['request_id']} has {len(opts)} payment options, expected 2-4"

    blank_amount_events = [e for e in ds.events if e["amount"] is None]
    for e in blank_amount_events:
        assert e["event_id"] in ds.images_by_event, f"{e['event_id']} has blank amount but no linked image"

    print(
        f"OK: {len(ds.requests)} requests, {len(ds.profiles)} profiles, {len(ds.events)} events, "
        f"{len(ds.exchange_rates)} exchange rates, {len(blank_amount_events)} blank-amount events "
        "all image-backed, every request has 2-4 payment options"
    )


if __name__ == "__main__":
    _self_check()
