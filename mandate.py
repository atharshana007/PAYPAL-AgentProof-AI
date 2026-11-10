import hashlib
import hmac
import json
import os

from dotenv import load_dotenv

import auditlog
import currency as currency_utils

load_dotenv()


def create_mandate(
    user,
    max_total,
    allowed_categories,
    allowed_merchants,
    expires_at,
    currency=currency_utils.DEFAULT_CURRENCY,
):
    """Create a JSON-ready mandate payload."""
    currency_utils.validate_currency(currency)
    return {
        "user": user,
        "max_total": max_total,
        "currency": currency,
        "allowed_categories": list(allowed_categories),
        "allowed_merchants": list(allowed_merchants),
        "expires_at": expires_at,
    }


def sign_mandate(mandate):
    secret = os.getenv("MANDATE_SECRET")
    if not secret:
        raise ValueError("MANDATE_SECRET is required to sign a mandate.")
    canonical = json.dumps(mandate, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_mandate(mandate, signature):
    if not isinstance(signature, str):
        return False
    try:
        expected = sign_mandate(mandate)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, signature)


def create_and_store(data):
    """Persist a signed mandate for the existing API route."""
    mandate_data = create_mandate(
        user=data.get("user", "demo-user"),
        max_total=data.get("max_total", data.get("budget")),
        allowed_categories=data["allowed_categories"],
        allowed_merchants=data["allowed_merchants"],
        expires_at=data["expires_at"],
        currency=data.get("currency", currency_utils.DEFAULT_CURRENCY),
    )
    signature = sign_mandate(mandate_data)
    canonical = json.dumps(mandate_data, sort_keys=True)
    with auditlog.connect() as db:
        db.execute(
            """INSERT OR REPLACE INTO mandates (id, data_json, signature)
               VALUES (1, ?, ?)""",
            (canonical, signature),
        )
    auditlog.append_event(
        "",
        "mandate_created",
        {
            "mandate": mandate_data,
            "signature": signature,
            "currency": mandate_data["currency"],
        },
    )
    return {"mandate": mandate_data, "signature": signature}


def get_current():
    with auditlog.connect() as db:
        row = db.execute(
            "SELECT data_json, signature FROM mandates WHERE id = 1"
        ).fetchone()
    if row is None:
        return None
    return {"mandate": json.loads(row["data_json"]), "signature": row["signature"]}
