from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import math

import mandate as mandate_signing


def _amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def check_policy(mandate, signature, request):
    """Return the policy decision and an explanation for a purchase request."""
    if not mandate_signing.verify_mandate(mandate, signature):
        return "BLOCK", "The mandate signature is invalid."

    try:
        expiry = datetime.fromisoformat(mandate["expires_at"])
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            return "BLOCK", "The mandate has expired."
    except (KeyError, TypeError, ValueError):
        return "BLOCK", "The mandate expiry is invalid."

    if request.get("merchant") not in mandate.get("allowed_merchants", []):
        return "BLOCK", "The merchant is not allowed by the mandate."
    if request.get("category") not in mandate.get("allowed_categories", []):
        return "BLOCK", "The category is not allowed by the mandate."

    amount = _amount(request.get("amount"))
    budget = _amount(mandate.get("max_total"))
    if amount is None or budget is None:
        return "BLOCK", "The purchase amount or mandate budget is invalid."
    if amount > budget:
        return "BLOCK", "The purchase exceeds the mandate budget."
    if amount > budget * Decimal("0.8"):
        return "NEEDS_APPROVAL", "The purchase is over 80% of the mandate budget."
    return "ALLOW", "The purchase is within the mandate policy."
