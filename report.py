import json
import os

from anthropic import Anthropic

import auditlog


def _event_data(event):
    data = event.get("data")
    if isinstance(data, str):
        return json.loads(data)
    return data or {}


def _template_summary(report):
    request = report["request"] or "No request was recorded"
    decision = report["decision"] or "No policy decision was recorded"
    reason = report["decision_reason"] or "No decision reason was recorded"
    order_text = (
        f"PayPal order {report['paypal_order_id']} was created."
        if report["paypal_order_id"]
        else "No PayPal order was recorded."
    )
    capture_text = (
        f"PayPal capture {report['capture_id']} was recorded."
        if report["capture_id"]
        else "No PayPal capture was recorded."
    )
    amount_text = (
        f"The authorized amount was {report['amount']} {report['currency']}."
        if report["amount"] is not None and report["currency"]
        else "No transaction amount or currency was recorded."
    )
    captured_amount_text = (
        f"The captured amount was {report['captured_amount']} {report['captured_currency']}."
        if report["captured_amount"] is not None and report["captured_currency"]
        else ""
    )
    return (
        f"The request was: {request}. The policy decision was {decision}: {reason}. "
        f"{amount_text} {order_text} {capture_text} {captured_amount_text}"
    )


def _summary(report):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _template_summary(report)

    facts = {
        key: report[key]
        for key in (
            "request",
            "reasoning",
            "mandate",
            "decision",
            "decision_reason",
            "paypal_order_id",
            "capture_id",
            "amount",
            "currency",
            "captured_amount",
            "captured_currency",
            "chain_intact",
        )
    }
    response = Anthropic(api_key=api_key).messages.create(
        model=os.getenv("MODEL_NAME", "claude-sonnet-5-5"),
        max_tokens=180,
        system=(
            "Write exactly 3 plain-English sentences summarizing the report. "
            "Use only facts present in the supplied JSON. Do not infer or add facts."
        ),
        messages=[{"role": "user", "content": json.dumps(facts, sort_keys=True)}],
    )
    return "\n".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )


def build_report(purchase_id):
    events = [
        event
        for event in auditlog.get_log()
        if event["purchase_id"] == purchase_id
    ]
    report = {
        "purchase_id": purchase_id,
        "request": None,
        "reasoning": None,
        "mandate": None,
        "decision": None,
        "decision_reason": None,
        "paypal_order_id": None,
        "capture_id": None,
        "amount": None,
        "currency": None,
        "captured_amount": None,
        "captured_currency": None,
        "chain_intact": auditlog.verify_chain()[0],
        "events": events,
    }

    order_ids = set()
    for event in events:
        data = _event_data(event)
        event_type = event["event_type"]
        if event_type == "agent_request":
            report["request"] = data.get("request")
        elif event_type == "agent_reasoning":
            report["reasoning"] = data.get("text")
        elif event_type == "mandate_used":
            report["mandate"] = data.get("mandate")
        elif event_type == "policy_decision":
            report["decision"] = data.get("decision")
            report["decision_reason"] = data.get("reason")
            purchase = data.get("purchase") or {}
            report["amount"] = purchase.get("amount")
            report["currency"] = (
                purchase.get("currency")
                or data.get("currency")
                or ("USD" if purchase.get("amount") is not None else None)
            )
        elif event_type == "paypal_order_created":
            report["paypal_order_id"] = data.get("order_id")
            report["amount"] = data.get("amount", report["amount"])
            report["currency"] = data.get("currency") or report["currency"]
            if data.get("order_id"):
                order_ids.add(data["order_id"])
        elif event_type == "paypal_captured":
            report["capture_id"] = data.get("capture_id")
            report["captured_amount"] = data.get("amount")
            report["captured_currency"] = data.get("currency")

    if order_ids and not report["capture_id"]:
        for event in auditlog.get_log():
            if event["purchase_id"] in order_ids:
                data = _event_data(event)
                if event["event_type"] == "paypal_captured":
                    report["capture_id"] = data.get("capture_id")
                    break

    report["summary"] = _summary(report)
    return report


def build_dispute_report(purchase_id):
    return build_report(purchase_id)
