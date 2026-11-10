from datetime import datetime, timedelta, timezone
import importlib
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import auditlog
import currency
import mandate


def _mandate(currency_code="INR"):
    return mandate.create_mandate(
        user="demo-user",
        max_total=2500,
        allowed_categories=["books"],
        allowed_merchants=["Demo Store"],
        expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        currency=currency_code,
    )


def test_currency_defaults_to_indian_rupee():
    assert currency.DEFAULT_CURRENCY == "INR"
    assert _mandate()["currency"] == "INR"


def test_currency_is_included_in_mandate_signature(monkeypatch):
    monkeypatch.setenv("MANDATE_SECRET", "test-only-secret")
    signed_mandate = _mandate("USD")
    signature = mandate.sign_mandate(signed_mandate)

    assert mandate.verify_mandate(signed_mandate, signature)
    signed_mandate["currency"] = "INR"
    assert not mandate.verify_mandate(signed_mandate, signature)


def test_unsupported_mandate_currency_is_rejected():
    with pytest.raises(ValueError, match="INR or USD"):
        _mandate("EUR")


def test_api_models_reject_unsupported_currency(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "api-currency.db"))
    main = importlib.import_module("main")

    with pytest.raises(ValidationError):
        main.MandateInput(
            budget=50,
            currency="EUR",
            allowed_categories=["books"],
            allowed_merchants=["Demo Store"],
            expires_at="2030-01-01T00:00:00Z",
        )

    with pytest.raises(ValidationError):
        main.AgentInput(request="Buy a book", currency="EUR")


def _record_authorized_order(currency_code="INR"):
    signed_mandate = _mandate("INR")
    signature = mandate.sign_mandate(signed_mandate)
    purchase_id = "purchase-currency-test"
    auditlog.append_event(
        purchase_id,
        "mandate_used",
        {
            "mandate": signed_mandate,
            "signature": signature,
            "currency": "INR",
        },
    )
    auditlog.append_event(
        purchase_id,
        "policy_decision",
        {
            "purchase": {
                "amount": 25,
                "currency": "INR",
                "item": "Book",
            },
            "decision": "ALLOW",
            "reason": "Within policy.",
            "currency": "INR",
        },
    )
    auditlog.append_event(
        purchase_id,
        "paypal_order_created",
        {
            "order_id": "ORDER-CURRENCY-TEST",
            "amount": "25",
            "currency": currency_code,
        },
    )


def test_capture_requires_order_currency_to_match_signed_mandate(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "capture-currency.db"))
    monkeypatch.setenv("MANDATE_SECRET", "test-only-secret")
    auditlog.init_db()
    main = importlib.import_module("main")
    _record_authorized_order(currency_code="USD")
    paypal_calls = []
    monkeypatch.setattr(
        main.paypal,
        "get_access_token",
        lambda: paypal_calls.append("token"),
    )

    with pytest.raises(HTTPException) as error:
        main.capture_paypal_order("ORDER-CURRENCY-TEST")

    assert error.value.status_code == 409
    assert paypal_calls == []


def test_successful_capture_audits_currency_and_amount(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "capture-success.db"))
    monkeypatch.setenv("MANDATE_SECRET", "test-only-secret")
    auditlog.init_db()
    main = importlib.import_module("main")
    _record_authorized_order()
    monkeypatch.setattr(main.paypal, "get_access_token", lambda: "token")
    capture_calls = []
    monkeypatch.setattr(
        main.paypal,
        "capture_order",
        lambda *args, **kwargs: capture_calls.append(kwargs)
        or {
            "status": "COMPLETED",
            "capture_id": "CAPTURE-CURRENCY-TEST",
            "amount": "25.00",
            "currency": "INR",
        },
    )

    result = main.capture_paypal_order("ORDER-CURRENCY-TEST")

    assert result["currency"] == "INR"
    assert capture_calls == [
        {"expected_currency": "INR", "expected_amount": "25"}
    ]
    capture_event = next(
        event
        for event in auditlog.get_log()
        if event["event_type"] == "paypal_captured"
    )
    assert capture_event["data"]["currency"] == "INR"
    assert capture_event["data"]["amount"] == "25.00"


def test_legacy_signed_usd_order_remains_capturable(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "legacy-capture.db"))
    monkeypatch.setenv("MANDATE_SECRET", "test-only-secret")
    auditlog.init_db()
    main = importlib.import_module("main")
    legacy_mandate = {
        "user": "demo-user",
        "max_total": 100,
        "allowed_categories": ["books"],
        "allowed_merchants": ["Demo Store"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    signature = mandate.sign_mandate(legacy_mandate)
    with auditlog.connect() as db:
        db.execute(
            "INSERT INTO mandates (id, data_json, signature) VALUES (1, ?, ?)",
            (json.dumps(legacy_mandate, sort_keys=True), signature),
        )
    purchase_id = "legacy-purchase"
    auditlog.append_event(
        purchase_id,
        "mandate_used",
        {"mandate": legacy_mandate},
    )
    auditlog.append_event(
        purchase_id,
        "policy_decision",
        {
            "purchase": {"amount": 25, "item": "Book"},
            "decision": "ALLOW",
            "reason": "Within policy.",
        },
    )
    auditlog.append_event(
        purchase_id,
        "paypal_order_created",
        {"order_id": "LEGACY-ORDER"},
    )
    capture_calls = []
    monkeypatch.setattr(main.paypal, "get_access_token", lambda: "token")
    monkeypatch.setattr(
        main.paypal,
        "capture_order",
        lambda *args, **kwargs: capture_calls.append(kwargs)
        or {
            "status": "COMPLETED",
            "capture_id": "LEGACY-CAPTURE",
            "amount": "25.00",
            "currency": "USD",
        },
    )

    result = main.capture_paypal_order("LEGACY-ORDER")

    assert result["currency"] == "USD"
    assert capture_calls == [{"expected_currency": "USD", "expected_amount": 25}]
