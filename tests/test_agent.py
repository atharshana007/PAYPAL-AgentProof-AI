from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import agent
import auditlog
import mandate
import paypal


@pytest.fixture
def signed_mandate(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "agent-test.db"))
    monkeypatch.setenv("MANDATE_SECRET", "test-only-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")
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
    monkeypatch.setattr(
        paypal,
        "create_order",
        lambda *args, **kwargs: {
            "order_id": "ORDER-123",
            "approval_link": "https://sandbox.example/approve",
        },
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
                },
            ),
        ],
    )

    result = agent.run_agent("Buy a book", rogue=False)

    assert result["decision"] == "ALLOW"
    assert result["reasoning"] == "A book fits your mandate."
    assert result["purchase_id"]
    assert result["order_id"] == "ORDER-123"
    assert result["approval_link"] == "https://sandbox.example/approve"
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
                },
            ),
        ],
    )

    result = agent.run_agent("Buy something", rogue=True)

    assert result["decision"] == "BLOCK"
    assert "category" in result["reason"]
    assert "misbehave" in calls["system"]


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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    auditlog.init_db()

    result = agent.run_agent("Buy a book")

    assert result["decision"] == "ERROR"
    assert "ANTHROPIC_API_KEY" in result["reason"]
