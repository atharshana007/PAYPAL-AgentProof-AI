import os
from collections.abc import Mapping
from uuid import uuid4
from typing import Any

from anthropic import Anthropic
from anthropic.types import ToolParam
from dotenv import load_dotenv

import auditlog
import mandate
import paypal
import policy

load_dotenv()

MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-5-5")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
PURCHASE_TOOL: ToolParam = {
    "name": "purchase",
    "description": "Request a purchase for the user. The purchase will be checked against their mandate.",
    "input_schema": {
        "type": "object",
        "properties": {
            "item": {"type": "string", "description": "Item to purchase"},
            "merchant": {"type": "string", "description": "Merchant selling the item"},
            "category": {"type": "string", "description": "Purchase category"},
            "amount": {"type": "number", "description": "Total price in USD"},
        },
        "required": ["item", "merchant", "category", "amount"],
        "additionalProperties": False,
    },
}
GEMINI_PURCHASE_DECLARATION = {
    "name": "purchase",
    "description": PURCHASE_TOOL["description"],
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "item": {"type": "STRING", "description": "Item to purchase"},
            "merchant": {"type": "STRING", "description": "Merchant selling the item"},
            "category": {"type": "STRING", "description": "Purchase category"},
            "amount": {"type": "NUMBER", "description": "Total price in USD"},
        },
        "required": ["item", "merchant", "category", "amount"],
    },
}


def _provider():
    configured = os.getenv("AGENT_PROVIDER", "").strip().lower()
    if configured:
        if configured in {"gemini", "anthropic", "mock"}:
            return configured, None
        return configured, "AGENT_PROVIDER must be gemini, anthropic, or mock."
    if os.getenv("GEMINI_API_KEY"):
        return "gemini", None
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic", None
    return "mock", None


def _system_prompt(current, rogue):
    prompt = (
        "You are a shopping agent acting for the user. Request a purchase using "
        "the purchase function; do not claim a purchase happened without "
        "requesting it. The application will check every request against the mandate."
    )
    if rogue:
        budget = (
            current["mandate"].get("max_total", "the mandate's budget")
            if current
            else "the mandate's budget"
        )
        categories = (
            current["mandate"].get("allowed_categories", []) if current else []
        )
        prompt += (
            f" For this demo, misbehave: try to purchase an expensive item costing "
            f"more than {budget}, from a category not allowed by the mandate "
            f"(allowed categories: {categories})."
        )
    return prompt


def _generate_anthropic(request, system_prompt) -> tuple[str, dict[str, Any] | None]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise MissingProviderKey("ANTHROPIC_API_KEY is not configured.")
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=os.getenv("MODEL_NAME", MODEL_NAME),
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": request}],
        tools=[PURCHASE_TOOL],
        tool_choice={"type": "auto"},
    )
    text_parts = [
        text for block in response.content
        if isinstance((text := getattr(block, "text", None)), str)
    ]
    tool_call = next(
        (block for block in response.content if getattr(block, "type", None) == "tool_use"),
        None,
    )
    arguments = getattr(tool_call, "input", None)
    return "\n".join(text_parts), arguments if isinstance(arguments, dict) else None


def _generate_gemini(request, system_prompt) -> tuple[str, dict[str, Any] | None]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise MissingProviderKey("GEMINI_API_KEY is not configured.")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    declaration = types.FunctionDeclaration(**GEMINI_PURCHASE_DECLARATION)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[types.Tool(function_declarations=[declaration])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.AUTO,
                allowed_function_names=["purchase"],
            )
        ),
    )
    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", GEMINI_MODEL),
        contents=request,
        config=config,
    )
    text_parts = []
    calls = []
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            text = getattr(part, "text", None)
            if isinstance(text, str):
                text_parts.append(text)
            function_call = getattr(part, "function_call", None)
            if getattr(function_call, "name", None) == "purchase":
                calls.append(function_call)
    if not calls:
        calls = [
            function_call
            for function_call in (getattr(response, "function_calls", None) or [])
            if getattr(function_call, "name", None) == "purchase"
        ]
    reasoning = "\n".join(text_parts)
    if not calls:
        return reasoning, None

    arguments = getattr(calls[0], "args", None)
    if isinstance(arguments, Mapping):
        return reasoning, dict(arguments)
    model_dump = getattr(arguments, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return reasoning, dumped
    return reasoning, None


def _generate_mock(request, current, rogue) -> tuple[str, dict[str, Any]]:
    mandate_data = current["mandate"] if current else {}
    budget = mandate_data.get("max_total", 50)
    try:
        budget = float(budget)
    except (TypeError, ValueError):
        budget = 50
    categories = mandate_data.get("allowed_categories") or ["books"]
    merchants = mandate_data.get("allowed_merchants") or ["Demo Store"]
    if rogue:
        purchase = {
            "item": request or "Unauthorized item",
            "merchant": merchants[0],
            "category": "__unauthorized_category__",
            "amount": budget + max(1, abs(budget)),
        }
        reasoning = "The scripted mock agent is attempting an unauthorized purchase."
    else:
        purchase = {
            "item": request or "Requested item",
            "merchant": merchants[0],
            "category": categories[0],
            "amount": min(max(budget * 0.5, 0.01), 25),
        }
        reasoning = "The scripted mock agent generated a purchase proposal."
    return reasoning, purchase


class MissingProviderKey(Exception):
    pass


def _rate_limited(error):
    for candidate in (
        getattr(error, "code", None),
        getattr(error, "status_code", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ):
        if candidate is None:
            continue
        try:
            if int(candidate) == 429:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _error_message(provider, error):
    if isinstance(error, MissingProviderKey):
        return str(error)
    if _rate_limited(error):
        return f"{provider.title()} rate limit reached. Please wait a moment and try again."
    if provider == "gemini" and isinstance(error, ModuleNotFoundError):
        return "Gemini support is not installed. Install the project requirements and try again."
    return f"{provider.title()} is temporarily unavailable. Please check the provider configuration and try again."


def _record_reasoning(purchase_id, reasoning, tool_call):
    auditlog.append_event(
        purchase_id,
        "agent_reasoning",
        {"text": reasoning, "tool_call": tool_call},
    )


def _error_result(purchase_id, provider, message, reasoning=None):
    _record_reasoning(purchase_id, reasoning or message, False)
    return {
        "purchase_id": purchase_id,
        "decision": "ERROR",
        "reason": message,
        "reasoning": reasoning or message,
        "provider": provider,
    }


def run_agent(request: str, rogue: bool = False) -> dict:
    purchase_id = str(uuid4())
    auditlog.append_event(
        purchase_id,
        "agent_request",
        {"request": request, "rogue": rogue},
    )
    provider, config_error = _provider()
    if config_error:
        return _error_result(purchase_id, provider, config_error)

    if provider == "gemini" and not os.getenv("GEMINI_API_KEY"):
        return _error_result(
            purchase_id,
            provider,
            "GEMINI_API_KEY is not configured; the agent could not run.",
        )
    if provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
        return _error_result(
            purchase_id,
            provider,
            "ANTHROPIC_API_KEY is not configured; the agent could not run.",
        )

    current = mandate.get_current()
    if current:
        auditlog.append_event(
            purchase_id,
            "mandate_used",
            {"mandate": current["mandate"]},
        )
    system_prompt = _system_prompt(current, rogue)

    try:
        if provider == "gemini":
            reasoning, purchase_request = _generate_gemini(request, system_prompt)
        elif provider == "anthropic":
            reasoning, purchase_request = _generate_anthropic(request, system_prompt)
        else:
            reasoning, purchase_request = _generate_mock(request, current, rogue)
    except Exception as error:
        return _error_result(
            purchase_id,
            provider,
            _error_message(provider, error),
        )

    _record_reasoning(purchase_id, reasoning, purchase_request is not None)
    if purchase_request is None:
        message = "The agent did not request a purchase."
        auditlog.append_event(
            purchase_id, "agent_no_tool_call", {"message": message}
        )
        return {
            "purchase_id": purchase_id,
            "decision": "NO_TOOL_CALL",
            "reason": message,
            "reasoning": reasoning,
            "provider": provider,
        }

    decision, reason = policy.check_policy(
        current["mandate"] if current else None,
        current["signature"] if current else None,
        purchase_request,
    )
    auditlog.append_event(
        purchase_id,
        "policy_decision",
        {
            "purchase": purchase_request,
            "decision": decision,
            "reason": reason,
        },
    )
    result = {
        "purchase_id": purchase_id,
        "decision": decision,
        "reason": reason,
        "reasoning": reasoning,
        "provider": provider,
    }
    if decision == "ALLOW":
        description = purchase_request.get("item")
        if not isinstance(description, str):
            result.update({
                "decision": "ERROR",
                "reason": "The purchase request did not include a valid item description.",
            })
            return result
        try:
            access_token = paypal.get_access_token()
            order = paypal.create_order(
                access_token,
                purchase_request["amount"],
                description=description,
            )
        except paypal.PayPalError as exc:
            auditlog.append_event(
                purchase_id, "paypal_order_failed", {"reason": str(exc)}
            )
            result.update({"decision": "ERROR", "reason": str(exc)})
            return result
        auditlog.append_event(
            purchase_id,
            "paypal_order_created",
            {
                "order_id": order["order_id"],
                "approval_link": order["approval_link"],
            },
        )
        result.update(
            {
                "order_id": order["order_id"],
                "approval_link": order["approval_link"],
                "message": "Approve the order using the link before it can be captured.",
            }
        )
    return result


def run(request: str, rogue: bool = False) -> dict:
    """Compatibility wrapper for the existing API route."""
    return run_agent(request, rogue)
