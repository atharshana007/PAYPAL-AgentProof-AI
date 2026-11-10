import requests
import pytest

import paypal


class MockResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)

    def json(self):
        return self.payload


def test_get_access_token_success(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("PAYPAL_SECRET", "client-secret")
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return MockResponse({"access_token": "sandbox-token"})

    monkeypatch.setattr(paypal.requests, "post", post)

    assert paypal.get_access_token() == "sandbox-token"
    assert seen["url"] == f"{paypal.SANDBOX_API}/v1/oauth2/token"
    assert seen["auth"] == ("client-id", "client-secret")
    assert seen["data"] == {"grant_type": "client_credentials"}
    assert seen["timeout"] == 15


def test_create_order_returns_id_and_approval_link(monkeypatch):
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return MockResponse(
            {
                "id": "ORDER-123",
                "links": [{"rel": "approve", "href": "https://sandbox/approve"}],
            }
        )

    monkeypatch.setattr(paypal.requests, "post", post)

    order = paypal.create_order("sandbox-token", 12.5, description="A book")

    assert order == {
        "order_id": "ORDER-123",
        "approval_link": "https://sandbox/approve",
    }
    assert seen["json"]["intent"] == "CAPTURE"
    assert seen["json"]["purchase_units"][0]["amount"] == {
        "currency_code": "USD",
        "value": "12.5",
    }
    assert seen["headers"]["Authorization"] == "Bearer sandbox-token"
    assert seen["timeout"] == 15


def test_capture_order_returns_status_and_capture_id(monkeypatch):
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return MockResponse(
            {
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAPTURE-123",
                                    "amount": {"currency_code": "USD", "value": "12.5"},
                                }
                            ]
                        }
                    }
                ],
            }
        )

    monkeypatch.setattr(paypal.requests, "post", post)

    capture = paypal.capture_order("sandbox-token", "ORDER-123")

    assert capture == {
        "status": "COMPLETED",
        "capture_id": "CAPTURE-123",
        "amount": "12.5",
        "currency": "USD",
    }
    assert seen["url"] == (
        f"{paypal.SANDBOX_API}/v2/checkout/orders/ORDER-123/capture"
    )
    assert seen["timeout"] == 15


def test_create_order_rejects_unsupported_currency(monkeypatch):
    with pytest.raises(ValueError, match="INR or USD"):
        paypal.create_order("sandbox-token", 12.5, currency="EUR")


def test_capture_order_validates_captured_currency_and_amount(monkeypatch):
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return MockResponse(
            {
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAPTURE-123",
                                    "amount": {"currency_code": "INR", "value": "1250.00"},
                                }
                            ]
                        }
                    }
                ],
            }
        )

    monkeypatch.setattr(paypal.requests, "post", post)

    capture = paypal.capture_order(
        "sandbox-token",
        "ORDER-123",
        expected_currency="INR",
        expected_amount="1250",
    )

    assert capture == {
        "status": "COMPLETED",
        "capture_id": "CAPTURE-123",
        "amount": "1250.00",
        "currency": "INR",
    }
    assert seen["headers"]["Authorization"] == "Bearer sandbox-token"


def test_capture_order_rejects_mismatched_captured_currency(monkeypatch):
    def post(url, **kwargs):
        return MockResponse(
            {
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAPTURE-123",
                                    "amount": {"currency_code": "USD", "value": "12.50"},
                                }
                            ]
                        }
                    }
                ],
            }
        )

    monkeypatch.setattr(paypal.requests, "post", post)
    with pytest.raises(paypal.PayPalError, match="currency"):
        paypal.capture_order("sandbox-token", "ORDER-123", expected_currency="INR")


def test_missing_credentials_raise_clear_error(monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_SECRET", raising=False)

    with pytest.raises(paypal.PayPalError, match="PAYPAL_CLIENT_ID and PAYPAL_SECRET"):
        paypal.get_access_token()


def test_http_error_has_clear_message_without_credentials(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "private-client")
    monkeypatch.setenv("PAYPAL_SECRET", "private-secret")

    def post(url, **kwargs):
        return MockResponse({"error": "invalid_client"}, status_code=401)

    monkeypatch.setattr(paypal.requests, "post", post)

    with pytest.raises(paypal.PayPalError, match="HTTP 401") as error:
        paypal.get_access_token()
    assert "private-client" not in str(error.value)
    assert "private-secret" not in str(error.value)
