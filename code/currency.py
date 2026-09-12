class MissingExchangeRateError(Exception):
    pass


def convert_to_home_currency(amount, from_currency, to_currency, rate_date, exchange_rates):
    if from_currency == to_currency:
        return amount
    key = (rate_date, from_currency, to_currency)
    if key not in exchange_rates:
        raise MissingExchangeRateError(
            f"no exchange_rates.csv row for {from_currency}->{to_currency} on {rate_date}"
        )
    return amount * exchange_rates[key]


def _self_check():
    import data_loader

    ds = data_loader.load_all()
    checked = 0
    for event in ds.events:
        user = ds.profiles[event["user_id"]]
        if event["currency"] == user["home_currency"] or event["amount"] is None:
            continue
        converted = convert_to_home_currency(
            event["amount"], event["currency"], user["home_currency"],
            event["settlement_date"], ds.exchange_rates,
        )
        assert converted > 0
        checked += 1
    print(f"OK: converted {checked} foreign-currency events to home currency with zero invented rates")


if __name__ == "__main__":
    _self_check()
