from datetime import datetime, timedelta, timezone

import auditlog
import report


def _setup_report_db(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "report-test.db"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    auditlog.init_db()


def _add_purchase_events(purchase_id, decision="ALLOW"):
    mandate_terms = {
        "user": "demo-user",
        "max_total": 100,
        "currency": "INR",
        "allowed_categories": ["books"],
        "allowed_merchants": ["Demo Store"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    auditlog.append_event(
        purchase_id, "agent_request", {"request": "Buy a book", "rogue": False}
    )
    auditlog.append_event(
        purchase_id, "mandate_used", {"mandate": mandate_terms}
    )
    auditlog.append_event(
        purchase_id,
        "agent_reasoning",
        {"text": "A book is requested.", "tool_call": True},
    )
    auditlog.append_event(
        purchase_id,
        "policy_decision",
        {
            "purchase": {
                "amount": 50,
                "currency": "INR",
                "item": "Book",
            },
            "decision": decision,
            "reason": "Matches mandate." if decision == "ALLOW" else "Category not allowed.",
            "currency": "INR",
        },
    )
    if decision == "ALLOW":
        auditlog.append_event(
            purchase_id,
            "paypal_order_created",
            {
                "order_id": "ORDER-123",
                "approval_link": "https://sandbox/approve",
                "amount": "50",
                "currency": "INR",
            },
        )
        auditlog.append_event(
            purchase_id,
            "paypal_captured",
            {
                "capture_id": "CAPTURE-123",
                "status": "COMPLETED",
                "amount": "50.00",
                "currency": "INR",
            },
        )


def test_build_report_for_normal_purchase(monkeypatch, tmp_path):
    _setup_report_db(monkeypatch, tmp_path)
    _add_purchase_events("purchase-1")

    result = report.build_report("purchase-1")

    assert result["request"] == "Buy a book"
    assert result["reasoning"] == "A book is requested."
    assert result["mandate"]["max_total"] == 100
    assert result["decision"] == "ALLOW"
    assert result["paypal_order_id"] == "ORDER-123"
    assert result["capture_id"] == "CAPTURE-123"
    assert result["amount"] == "50"
    assert result["currency"] == "INR"
    assert result["captured_amount"] == "50.00"
    assert result["captured_currency"] == "INR"
    assert result["chain_intact"] is True
    assert "Matches mandate." in result["summary"]


def test_build_report_for_blocked_purchase(monkeypatch, tmp_path):
    _setup_report_db(monkeypatch, tmp_path)
    _add_purchase_events("purchase-blocked", decision="BLOCK")

    result = report.build_report("purchase-blocked")

    assert result["decision"] == "BLOCK"
    assert result["decision_reason"] == "Category not allowed."
    assert result["paypal_order_id"] is None
    assert result["capture_id"] is None
    assert "BLOCK" in result["summary"]


def test_report_marks_tampered_chain(monkeypatch, tmp_path):
    _setup_report_db(monkeypatch, tmp_path)
    _add_purchase_events("purchase-tampered")
    first_event = auditlog.get_log()[0]
    with auditlog.connect() as db:
        db.execute(
            "UPDATE events SET data = ? WHERE id = ?",
            ('{"request":"altered"}', first_event["id"]),
        )

    result = report.build_report("purchase-tampered")

    assert result["chain_intact"] is False
