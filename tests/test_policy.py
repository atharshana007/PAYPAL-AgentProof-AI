from datetime import datetime, timedelta, timezone

import pytest

import mandate as mandate_module
import policy


@pytest.fixture
def signed_mandate(monkeypatch):
    monkeypatch.setenv("MANDATE_SECRET", "test-only-secret")
    current = datetime.now(timezone.utc)
    data = mandate_module.create_mandate(
        user="demo-user",
        max_total=100,
        allowed_categories=["books"],
        allowed_merchants=["Demo Store"],
        expires_at=(current + timedelta(days=1)).isoformat(),
    )
    return data, mandate_module.sign_mandate(data)


def request(amount=50, category="books", merchant="Demo Store"):
    return {
        "amount": amount,
        "category": category,
        "merchant": merchant,
        "currency": "INR",
    }


def test_allowed_purchase(signed_mandate):
    data, signature = signed_mandate
    assert policy.check_policy(data, signature, request()) == (
        "ALLOW",
        "The purchase is within the mandate policy.",
    )


def test_purchase_over_budget_is_blocked(signed_mandate):
    data, signature = signed_mandate
    decision, reason = policy.check_policy(data, signature, request(amount=101))
    assert decision == "BLOCK"
    assert "exceeds" in reason


def test_wrong_category_is_blocked(signed_mandate):
    data, signature = signed_mandate
    decision, reason = policy.check_policy(
        data, signature, request(category="electronics")
    )
    assert decision == "BLOCK"
    assert "category" in reason


def test_wrong_merchant_is_blocked(signed_mandate):
    data, signature = signed_mandate
    decision, reason = policy.check_policy(
        data, signature, request(merchant="Other Store")
    )
    assert decision == "BLOCK"
    assert "merchant" in reason


def test_expired_mandate_is_blocked(signed_mandate):
    data, _ = signed_mandate
    data["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    signature = mandate_module.sign_mandate(data)
    decision, reason = policy.check_policy(data, signature, request())
    assert decision == "BLOCK"
    assert "expired" in reason


def test_tampered_mandate_is_blocked(signed_mandate):
    data, signature = signed_mandate
    data["max_total"] = 1000
    decision, reason = policy.check_policy(data, signature, request())
    assert decision == "BLOCK"
    assert "signature" in reason


def test_purchase_over_80_percent_needs_approval(signed_mandate):
    data, signature = signed_mandate
    decision, reason = policy.check_policy(data, signature, request(amount=81))
    assert decision == "NEEDS_APPROVAL"
    assert "80%" in reason


def test_purchase_currency_must_match_signed_mandate(signed_mandate):
    data, signature = signed_mandate
    decision, reason = policy.check_policy(
        data, signature, {**request(), "currency": "USD"}
    )
    assert decision == "BLOCK"
    assert "currency" in reason


def test_purchase_currency_must_be_supported(signed_mandate):
    data, signature = signed_mandate
    decision, reason = policy.check_policy(
        data, signature, {**request(), "currency": "EUR"}
    )
    assert decision == "BLOCK"
    assert "currency" in reason
