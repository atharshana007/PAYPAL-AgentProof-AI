SUPPORTED_CURRENCIES = {"INR", "USD"}
DEFAULT_CURRENCY = "INR"
LEGACY_CURRENCY = "USD"


def validate_currency(currency):
    if not isinstance(currency, str) or currency not in SUPPORTED_CURRENCIES:
        raise ValueError("Currency must be INR or USD.")
    return currency


def mandate_currency(mandate):
    """Return a mandate's currency, treating pre-currency mandates as USD."""
    return validate_currency(mandate.get("currency", LEGACY_CURRENCY))
