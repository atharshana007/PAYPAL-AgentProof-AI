from contextlib import asynccontextmanager
from pathlib import Path
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

import agent
import auditlog
import mandate
import paypal
import report

auditlog.init_db()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    print("AgentProof AI running at http://127.0.0.1:8765", flush=True)
    yield


app = FastAPI(title="AgentProof AI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


class MandateInput(BaseModel):
    budget: float
    allowed_categories: list[str]
    allowed_merchants: list[str]
    expires_at: str


class AgentInput(BaseModel):
    request: str
    rogue: bool = False


@app.get("/")
def home():
    return FileResponse(
        Path("static") / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health")
def health():
    return {"app": "AgentProof AI", "port": 8765, "status": "ok"}


@app.post("/mandate")
def create_mandate(payload: MandateInput):
    try:
        return mandate.create_and_store(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/mandate")
def get_mandate():
    return mandate.get_current()


@app.post("/agent/run")
def run_agent(payload: AgentInput):
    return agent.run_agent(payload.request, payload.rogue)


@app.post("/paypal/capture/{order_id}")
def capture_paypal_order(order_id: str):
    try:
        access_token = paypal.get_access_token()
        capture = paypal.capture_order(access_token, order_id)
    except paypal.PayPalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    related_purchase_id = next(
        (
            event["purchase_id"]
            for event in reversed(auditlog.get_log())
            if event["event_type"] == "paypal_order_created"
            and event["data"].get("order_id") == order_id
        ),
        order_id,
    )
    auditlog.append_event(
        related_purchase_id,
        "paypal_captured",
        {"capture_id": capture["capture_id"], "status": capture["status"]},
    )
    return {"order_id": order_id, **capture}


@app.get("/log")
def get_log():
    return auditlog.get_log()


@app.get("/log/verify")
def verify_log():
    valid, broken_entry_id = auditlog.verify_chain()
    return {"valid": valid, "broken_entry_id": broken_entry_id}


@app.post("/log/tamper")
def tamper_log():
    try:
        return auditlog.tamper_oldest_entry()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/dispute/{purchase_id}")
def dispute_report(purchase_id: str):
    return report.build_report(purchase_id)
