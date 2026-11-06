"""PayPal Sandbox OAuth and Orders API helpers."""

import os

import requests

SANDBOX_API = "https://api-m.sandbox.paypal.com"
REQUEST_TIMEOUT = 15


class PayPalError(RuntimeError):
    """Raised when a PayPal Sandbox operation cannot be completed."""


def _response_json(response, operation):
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        status = response.status_code
        raise PayPalError(f"PayPal {operation} failed with HTTP {status}.") from exc
    try:
        return response.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise PayPalError(f"PayPal {operation} returned invalid JSON.") from exc


def get_access_token():
    client_id = os.getenv("PAYPAL_CLIENT_ID")
    secret = os.getenv("PAYPAL_SECRET")
    if not client_id or not secret:
        raise PayPalError(
            "PayPal sandbox credentials are missing; set PAYPAL_CLIENT_ID and PAYPAL_SECRET."
        )

    response = requests.post(
        f"{SANDBOX_API}/v1/oauth2/token",
        auth=(client_id, secret),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        timeout=REQUEST_TIMEOUT,
    )
    payload = _response_json(response, "access token request")
    token = payload.get("access_token")
    if not token:
        raise PayPalError("PayPal access token response did not contain an access token.")
    return token


def create_order(access_token, amount, currency="USD", description=""):
    response = requests.post(
        f"{SANDBOX_API}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {"currency_code": currency, "value": str(amount)},
                    "description": description,
                }
            ],
        },
        timeout=REQUEST_TIMEOUT,
    )
    payload = _response_json(response, "order creation")
    order_id = payload.get("id")
    approval_link = next(
        (
            link.get("href")
            for link in payload.get("links", [])
            if link.get("rel") == "approve"
        ),
        None,
    )
    if not order_id or not approval_link:
        raise PayPalError("PayPal order response is missing its id or approval link.")
    return {"order_id": order_id, "approval_link": approval_link}


def capture_order(access_token, order_id):
    response = requests.post(
        f"{SANDBOX_API}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={},
        timeout=REQUEST_TIMEOUT,
    )
    payload = _response_json(response, "order capture")
    captures = [
        capture
        for unit in payload.get("purchase_units", [])
        for capture in unit.get("payments", {}).get("captures", [])
    ]
    capture_id = captures[0].get("id") if captures else None
    status = payload.get("status")
    if not status or not capture_id:
        raise PayPalError("PayPal capture response is missing its status or capture id.")
    return {"status": status, "capture_id": capture_id}
