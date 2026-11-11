from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from google import genai

import agent
import auditlog
import mandate
import paypal


@pytest.fixture
def signed_mandate(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "agent-test.db"))
    monkeypatch.setenv("MANDATE_SECRET", "test-only-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")
    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    auditlog.init_db()
    data = mandate.create_mandate(
        user="demo-user",
        max_total=100,
        allowed_categories=["books"],
        allowed_merchants=["Demo Store"],
        expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    saved = {"mandate": data, "signature": mandate.sign_mandate(data)}
    monkeypatch.setattr(mandate, "get_current", lambda: saved)
    return saved


def mock_response(monkeypatch, content):
    calls = {}

    class MockMessages:
        def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(content=content)

    class MockAnthropic:
        def __init__(self, api_key):
            assert api_key == "test-api-key"
            self.messages = MockMessages()

    monkeypatch.setattr(agent, "Anthropic", MockAnthropic)
    return calls


def test_allowed_purchase_is_checked_and_returned(monkeypatch, signed_mandate):
    monkeypatch.setattr(paypal, "get_access_token", lambda: "test-access-token")
    created_orders = []

    def create_order(*args, **kwargs):
        created_orders.append((args, kwargs))
        return {
            "order_id": "ORDER-123",
            "approval_link": "https://sandbox.example/approve",
        }

    monkeypatch.setattr(
        paypal,
        "create_order",
        create_order,
    )
    calls = mock_response(
        monkeypatch,
        [
            SimpleNamespace(type="text", text="A book fits your mandate."),
            SimpleNamespace(
                type="tool_use",
                input={
                    "item": "Book",
                    "merchant": "Demo Store",
                    "category": "books",
                    "amount": 50,
                    "currency": "INR",
                },
            ),
        ],
    )

    result = agent.run_agent("Buy a book", rogue=False)

    assert result["decision"] == "ALLOW"
    assert result["provider"] == "anthropic"
    assert result["reasoning"] == "A book fits your mandate."
    assert result["purchase_id"]
    assert result["order_id"] == "ORDER-123"
    assert result["approval_link"] == "https://sandbox.example/approve"
    assert created_orders[0][1]["currency"] == "INR"
    assert calls["tools"][0]["name"] == "purchase"
    events = [event for event in auditlog.get_log() if event["purchase_id"] == result["purchase_id"]]
    assert [event["event_type"] for event in events] == [
        "agent_request",
        "mandate_used",
        "agent_reasoning",
        "policy_decision",
        "paypal_order_created",
    ]


def test_rogue_purchase_is_blocked(monkeypatch, signed_mandate):
    calls = mock_response(
        monkeypatch,
        [
            SimpleNamespace(type="text", text="Trying an unauthorized item."),
            SimpleNamespace(
                type="tool_use",
                input={
                    "item": "Expensive laptop",
                    "merchant": "Demo Store",
                    "category": "electronics",
                    "amount": 500,
                    "currency": "INR",
                },
            ),
        ],
    )

    result = agent.run_agent("Buy something", rogue=True)

    assert result["decision"] == "BLOCK"
    assert "category" in result["reason"]
    assert "misbehave" in calls["system"]


def test_selected_currency_cannot_override_signed_mandate(
    monkeypatch, signed_mandate
):
    generated = []
    monkeypatch.setattr(
        agent,
        "_generate_anthropic",
        lambda request, system_prompt: generated.append(True),
    )

    result = agent.run_agent("Buy a book", currency="USD")

    assert result["decision"] == "BLOCK"
    assert "signed mandate" in result["reason"]
    assert generated == []
    event = next(
        event
        for event in auditlog.get_log()
        if event["purchase_id"] == result["purchase_id"]
        and event["event_type"] == "policy_decision"
    )
    assert event["data"]["currency"] == "USD"


def test_usd_signed_mandate_creates_usd_paypal_order(monkeypatch, signed_mandate):
    current = signed_mandate["mandate"]
    usd_mandate = mandate.create_mandate(
        user=current["user"],
        max_total=current["max_total"],
        allowed_categories=current["allowed_categories"],
        allowed_merchants=current["allowed_merchants"],
        expires_at=current["expires_at"],
        currency="USD",
    )
    saved = {
        "mandate": usd_mandate,
        "signature": mandate.sign_mandate(usd_mandate),
    }
    monkeypatch.setattr(mandate, "get_current", lambda: saved)
    monkeypatch.setattr(paypal, "get_access_token", lambda: "test-access-token")
    created_orders = []
    monkeypatch.setattr(
        paypal,
        "create_order",
        lambda *args, **kwargs: created_orders.append(kwargs)
        or {
            "order_id": "USD-ORDER",
            "approval_link": "https://sandbox.example/usd-approve",
        },
    )
    mock_response(
        monkeypatch,
        [
            SimpleNamespace(type="text", text="A book fits your mandate."),
            SimpleNamespace(
                type="tool_use",
                input={
                    "item": "Book",
                    "merchant": "Demo Store",
                    "category": "books",
                    "amount": 50,
                    "currency": "USD",
                },
            ),
        ],
    )

    result = agent.run_agent("Buy a book", currency="USD")

    assert result["decision"] == "ALLOW"
    assert result["currency"] == "USD"
    assert created_orders == [{"currency": "USD", "description": "Book"}]


def test_no_tool_call_returns_clear_message(monkeypatch, signed_mandate):
    mock_response(
        monkeypatch,
        [SimpleNamespace(type="text", text="I need more details before buying.")],
    )

    result = agent.run_agent("Buy something", rogue=False)

    assert result["decision"] == "NO_TOOL_CALL"
    assert "did not request a purchase" in result["reason"]
    events = [event for event in auditlog.get_log() if event["purchase_id"] == result["purchase_id"]]
    assert [event["event_type"] for event in events] == [
        "agent_request",
        "mandate_used",
        "agent_reasoning",
        "agent_no_tool_call",
    ]


def test_missing_api_key_returns_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "missing-key.db"))
    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    auditlog.init_db()

    result = agent.run_agent("Buy a book")

    assert result["decision"] == "ERROR"
    assert "ANTHROPIC_API_KEY" in result["reason"]
    assert result["provider"] == "anthropic"


def mock_gemini_response(monkeypatch, response):
    calls = {}

    class MockModels:
        def generate_content(self, **kwargs):
            calls.update(kwargs)
            if isinstance(response, Exception):
                raise response
            return response

    class MockClient:
        def __init__(self, api_key):
            assert api_key == "test-gemini-key"
            self.models = MockModels()

    monkeypatch.setattr(genai, "Client", MockClient)
    monkeypatch.setenv("AGENT_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-gemini-model")
    return calls


def gemini_function_call(purchase):
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(text="I checked the proposed purchase."),
                        SimpleNamespace(
                            text=None,
                            function_call=SimpleNamespace(name="purchase", args=purchase),
                        ),
                    ]
                )
            )
        ]
    )


def test_gemini_allowed_purchase_is_checked_without_automatic_execution(
    monkeypatch, signed_mandate
):
    monkeypatch.setattr(paypal, "get_access_token", lambda: "test-access-token")
    monkeypatch.setattr(
        paypal,
        "create_order",
        lambda *args, **kwargs: {
            "order_id": "GEMINI-ORDER",
            "approval_link": "https://sandbox.example/gemini-approve",
        },
    )
    purchase = {
        "item": "Book",
        "merchant": "Demo Store",
        "category": "books",
        "amount": 50,
        "currency": "INR",
    }
    calls = mock_gemini_response(monkeypatch, gemini_function_call(purchase))

    result = agent.run_agent("Buy a book")

    assert result["decision"] == "ALLOW"
    assert result["provider"] == "gemini"
    assert result["order_id"] == "GEMINI-ORDER"
    assert calls["model"] == "test-gemini-model"
    assert calls["config"].automatic_function_calling.disable
    declarations = calls["config"].tools[0].function_declarations
    assert len(declarations) == 1
    assert declarations[0].name == "purchase"
    assert declarations[0].parameters.required == [
        "item",
        "merchant",
        "category",
        "amount",
        "currency",
    ]
    events = [
        event for event in auditlog.get_log()
        if event["purchase_id"] == result["purchase_id"]
    ]
    assert [event["event_type"] for event in events][-2:] == [
        "policy_decision",
        "paypal_order_created",
    ]


def test_gemini_rogue_purchase_is_blocked_without_order(monkeypatch, signed_mandate):
    calls = mock_gemini_response(
        monkeypatch,
        gemini_function_call(
            {
                "item": "Expensive laptop",
                "merchant": "Demo Store",
                "category": "electronics",
                "amount": 500,
                "currency": "INR",
            }
        ),
    )
    created_orders = []
    monkeypatch.setattr(paypal, "create_order", lambda *args, **kwargs: created_orders.append(args))

    result = agent.run_agent("Buy something", rogue=True)

    assert result["decision"] == "BLOCK"
    assert result["provider"] == "gemini"
    assert "category" in result["reason"]
    assert "misbehave" in calls["config"].system_instruction
    assert created_orders == []
    policy_event = next(
        event for event in auditlog.get_log()
        if event["purchase_id"] == result["purchase_id"]
        and event["event_type"] == "policy_decision"
    )
    assert policy_event["data"]["decision"] == "BLOCK"


def test_gemini_without_function_call_returns_clear_message(monkeypatch, signed_mandate):
    mock_gemini_response(
        monkeypatch,
        SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(
                                text="I need more details before buying.",
                                function_call=None,
                            )
                        ]
                    )
                )
            ]
        ),
    )

    result = agent.run_agent("Buy something")

    assert result["decision"] == "NO_TOOL_CALL"
    assert result["provider"] == "gemini"
    assert "did not request a purchase" in result["reason"]
    events = [
        event for event in auditlog.get_log()
        if event["purchase_id"] == result["purchase_id"]
    ]
    assert [event["event_type"] for event in events][-2:] == [
        "agent_reasoning",
        "agent_no_tool_call",
    ]


def test_missing_gemini_key_returns_friendly_error_without_exposing_key(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "missing-gemini-key.db"))
    monkeypatch.setenv("AGENT_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-be-shown")
    auditlog.init_db()

    result = agent.run_agent("Buy a book")

    assert result["decision"] == "ERROR"
    assert result["provider"] == "gemini"
    assert "GEMINI_API_KEY" in result["reason"]
    assert "should-not-be-shown" not in result["reason"]


def test_gemini_rate_limit_returns_friendly_message(monkeypatch, signed_mandate):
    class RateLimitError(Exception):
        code = 429

    mock_gemini_response(monkeypatch, RateLimitError("private provider response"))

    result = agent.run_agent("Buy a book")

    assert result["decision"] == "ERROR"
    assert result["provider"] == "gemini"
    assert "rate limit" in result["reason"].lower()
    assert "private provider response" not in result["reason"]
    assert "test-gemini-key" not in result["reason"]


def test_provider_auto_selects_gemini_before_anthropic(monkeypatch, signed_mandate):
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")
    monkeypatch.setattr(
        agent,
        "_generate_gemini",
        lambda request, system_prompt: ("No purchase requested.", None),
    )

    result = agent.run_agent("Buy a book")

    assert result["provider"] == "gemini"
    assert result["decision"] == "NO_TOOL_CALL"


def test_provider_defaults_to_mock_without_provider_keys(monkeypatch, signed_mandate):
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mandate_data = mandate.create_mandate(
        user="demo-user",
        max_total=100,
        allowed_categories=["accessories"],
        allowed_merchants=["Demo Accessories Shop", "Flipkart"],
        expires_at=signed_mandate["mandate"]["expires_at"],
        currency="INR",
    )
    saved_mandate = {
        "mandate": mandate_data,
        "signature": mandate.sign_mandate(mandate_data),
    }
    monkeypatch.setattr(mandate, "get_current", lambda: saved_mandate)
    monkeypatch.setattr(paypal, "get_access_token", lambda: "test-access-token")
    monkeypatch.setattr(
        paypal,
        "create_order",
        lambda *args, **kwargs: {
            "order_id": "MOCK-ORDER",
            "approval_link": "https://sandbox.example/mock-approve",
        },
    )

    result = agent.run_agent("Buy a book")

    assert result["provider"] == "mock"
    assert result["decision"] == "ALLOW"
    assert result["product_name"] == "Braided USB-C Cable"
    assert result["price"] == 49
    result_events = [
        event
        for event in auditlog.get_log()
        if event["purchase_id"] == result["purchase_id"]
    ]
    reasoning = next(
        event for event in result_events if event["event_type"] == "agent_reasoning"
    )
    decision = next(
        event for event in result_events if event["event_type"] == "policy_decision"
    )
    for event in (reasoning, decision):
        assert event["data"]["product_name"] == "Braided USB-C Cable"
        assert event["data"]["product_image"] == "/static/images/usb-c-cable.svg"
        assert event["data"]["price"] == 49


def test_mock_proposal_uses_india_currency_without_a_mandate():
    _, purchase = agent._generate_mock("Buy a book", None, rogue=False)

    assert purchase["currency"] == "INR"


def test_mock_electronics_purchase_uses_signed_usd_catalog_price(
    monkeypatch, signed_mandate
):
    current = signed_mandate["mandate"]
    usd_mandate = mandate.create_mandate(
        user=current["user"],
        max_total=100,
        allowed_categories=["electronics"],
        allowed_merchants=["Demo Accessories Shop", "Flipkart"],
        expires_at=current["expires_at"],
        currency="USD",
    )
    saved_mandate = {
        "mandate": usd_mandate,
        "signature": mandate.sign_mandate(usd_mandate),
    }
    monkeypatch.setattr(mandate, "get_current", lambda: saved_mandate)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(paypal, "get_access_token", lambda: "test-access-token")
    monkeypatch.setattr(
        paypal,
        "create_order",
        lambda *args, **kwargs: {
            "order_id": "USD-CATALOG-ORDER",
            "approval_link": "https://sandbox.example/usd-catalog-order",
        },
    )

    result = agent.run_agent("Buy electronics", currency="USD")

    assert result["decision"] == "ALLOW"
    assert result["product_name"] == "Portable Bluetooth Speaker"
    assert result["product_image"] == "/static/images/bluetooth-speaker.svg"
    assert result["price"] == 39.99
    assert result["currency"] == "USD"
