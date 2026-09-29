"""FastAPI entrypoint: Slack events, interactive buttons, slash commands, and the Live Office API."""
from __future__ import annotations

import asyncio
import json
import os
from urllib.parse import parse_qs

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .agents import FakeRunner, SDKRunner
from . import states
from .config import get_config
from .db import Approval, AuditEvent, Pause, Task, make_sessionmaker
from .dispatcher import Dispatcher, _month
from .live import sse
from .slack import SlackClient, parse_event, verify_signature

app = FastAPI(title="AI Workforce Dispatcher")
if os.environ.get("WORKFORCE_FRONTEND_ORIGIN"):
    app.add_middleware(CORSMiddleware, allow_origins=os.environ["WORKFORCE_FRONTEND_ORIGIN"].split(","),
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "Last-Event-ID"])
_background: set[asyncio.Task] = set()


def _dispatcher() -> Dispatcher:
    if not hasattr(app.state, "dispatcher"):
        runner = FakeRunner() if os.environ.get("WORKFORCE_RUNNER") == "fake" else SDKRunner()
        app.state.dispatcher = Dispatcher(get_config(), make_sessionmaker(), runner, SlackClient())
    return app.state.dispatcher


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _background.add(t)
    t.add_done_callback(_background.discard)


async def _verified_body(request: Request, ts: str | None, sig: str | None) -> bytes:
    body = await request.body()
    secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    if not verify_signature(secret, ts or "", body, sig or ""):
        raise HTTPException(401, "bad signature")
    return body


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/slack/events")
async def slack_events(request: Request, x_slack_request_timestamp: str | None = Header(None),
                       x_slack_signature: str | None = Header(None), x_slack_retry_num: str | None = Header(None)):
    body = await _verified_body(request, x_slack_request_timestamp, x_slack_signature)
    payload = json.loads(body)
    if payload.get("type") == "url_verification":
        return PlainTextResponse(payload["challenge"])
    msg = parse_event(payload)
    if msg is not None:
        _spawn(_dispatcher().handle_message(msg))  # dedupe by event_id handles Slack retries
    return JSONResponse({"ok": True})  # ack within 3s


@app.post("/slack/interactions")
async def slack_interactions(request: Request, x_slack_request_timestamp: str | None = Header(None),
                             x_slack_signature: str | None = Header(None)):
    body = await _verified_body(request, x_slack_request_timestamp, x_slack_signature)
    payload = json.loads(parse_qs(body.decode())["payload"][0])
    if payload.get("type") != "block_actions":
        return JSONResponse({"ok": True})
    user = payload["user"]["id"]
    ticks = [o["value"] for o in (((payload.get("state") or {}).get("values") or {}).get("memory", {})
                                  .get("memory_ticks", {}).get("selected_options") or [])]
    for act in payload.get("actions", []):
        if act.get("action_id") not in ("approve", "reject"):
            continue
        v = json.loads(act["value"])
        _spawn(_dispatcher().on_approval(user, v["approval_id"], act["action_id"] == "approve",
                                         button_hash=v.get("action_hash"), memory_ticks=ticks))
    return JSONResponse({"ok": True})


@app.post("/slack/commands")
async def slack_commands(request: Request, x_slack_request_timestamp: str | None = Header(None),
                         x_slack_signature: str | None = Header(None)):
    body = await _verified_body(request, x_slack_request_timestamp, x_slack_signature)
    form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
    return JSONResponse({"response_type": "ephemeral",
                         "text": _dispatcher().command(form.get("user_id", ""), form.get("text", ""))})


def _require_api_token(authorization: str | None, query_token: str | None = None) -> None:
    """The API token is the owner's key. `?token=` exists only because browser EventSource can't send headers."""
    token = os.environ.get("WORKFORCE_API_TOKEN")
    if not token or (authorization != f"Bearer {token}" and query_token != token):
        raise HTTPException(401, "unauthorized")


@app.get("/api/tasks")
async def list_tasks(authorization: str | None = Header(None)):
    """Read-only, for the future Vercel frontend. No agent context or audit payloads exposed."""
    _require_api_token(authorization)
    d = _dispatcher()
    with d.Session() as db:
        rows = db.scalars(select(Task).order_by(Task.created_at.desc()).limit(100))
        return [{"id": t.id, "department": t.department, "status": t.status, "size": t.size,
                 "objective": (t.contract or {}).get("objective"), "cost_usd": round(t.cost_usd, 4),
                 "created_at": t.created_at.isoformat()} for t in rows]


# ====================================================================== Live Office API
def _employee_json(d: Dispatcher, e) -> dict:
    return {"id": e.id, "name": e.name, "kind": e.kind, "department": e.dept or "hq", "model": e.model,
            "role": list(e.does), "does_not": list(e.does_not), "voice": (e.personality or {}).get("voice", []),
            "signoff": (e.personality or {}).get("signoff"), "promptable": e.kind in ("lead", "router")}


def _task_json(t: Task, holder: str | None = None) -> dict:
    c = t.contract or {}
    return {"id": t.id, "parent_id": t.parent_id, "department": t.department, "status": t.status, "size": t.size,
            "request": t.original_request[:500], "objective": c.get("objective"), "holder": holder,
            "contract_version": t.contract_version, "revisions": t.revisions, "cost_usd": round(t.cost_usd, 4),
            "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat() if t.updated_at else None}


def _approval_json(a: Approval) -> dict:
    p = a.preview or {}
    return {"id": a.id, "task_id": a.task_id, "gate": a.gate, "tier": a.tier, "action": a.action,
            "action_hash": a.action_hash, "contract_version": a.contract_version, "status": a.status,
            "employee_id": p.get("employee"), "preview": p, "created_at": a.created_at.isoformat()}


@app.get("/api/office")
async def office(authorization: str | None = Header(None)):
    """Static floor plan: every department, who sits where, who can be prompted. Rarely changes."""
    _require_api_token(authorization)
    d = _dispatcher()
    cfg = d.cfg
    depts = []
    for key, raw in cfg.org["departments"].items():
        depts.append({"id": key, "channel": raw["channel"],
                      "lead": _employee_json(d, cfg.employee(cfg.leads[key])),
                      "specialists": [_employee_json(d, e) for e in cfg.specialists_of(key)]})
    core = {k: _employee_json(d, cfg.employee(k)) for k in cfg.org["core"]}
    return {"company": cfg.org.get("company"), "owner": {"id": "owner"}, "core": core, "departments": depts,
            "monthly_budget_usd": d.monthly_budget}


@app.get("/api/office/state")
async def office_state(authorization: str | None = Header(None)):
    """Snapshot to draw the office right now. Then apply /api/live events with seq > snapshot.seq."""
    _require_api_token(authorization)
    d = _dispatcher()
    snap = d.live.snapshot()
    with d.Session() as db:
        open_tasks = [_task_json(t, snap["holders"].get(t.id)) for t in db.scalars(
            select(Task).where(Task.status.notin_(list(states.TERMINAL))).order_by(Task.created_at))]
        approvals = [_approval_json(a) for a in db.scalars(select(Approval).where(Approval.status == "pending"))]
        spent = d.policy.counter_value(db, f"month:{_month()}", "plan", "llm_usd")
        pauses = [{"scope": p.scope, "reason": p.reason} for p in db.scalars(select(Pause))]
    return {"seq": snap["seq"], "presence": snap["presence"], "open_tasks": open_tasks,
            "pending_approvals": approvals, "month_spent_usd": round(spent, 4),
            "month_budget_usd": d.monthly_budget, "pauses": pauses}


@app.get("/api/live")
async def live(authorization: str | None = Header(None), token: str | None = Query(None),
               since: int | None = Query(None), last_event_id: str | None = Header(None)):
    """Server-Sent Events. Reconnects resume from Last-Event-ID automatically."""
    _require_api_token(authorization, token)
    start = since if since is not None else (int(last_event_id) if (last_event_id or "").isdigit() else None)
    return StreamingResponse(sse(_dispatcher().live, start), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class PromptIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


@app.post("/api/desks/{employee_id}/prompt", status_code=202)
async def prompt_desk(employee_id: str, body: PromptIn, authorization: str | None = Header(None)):
    """Owner clicks Atlas's or a Lead's desk and gives a task."""
    _require_api_token(authorization)
    d = _dispatcher()
    if employee_id not in d.cfg.employees:
        raise HTTPException(404, "no such employee")
    try:
        tid = d.open_office_task(employee_id, body.text.strip())
    except ValueError as e:
        raise HTTPException(403, str(e))
    _spawn(d.draft_contract(tid))
    return {"task_id": tid}


@app.post("/api/tasks/{task_id}/reply", status_code=202)
async def reply_task(task_id: str, body: PromptIn, authorization: str | None = Header(None)):
    """Owner answers a Lead's question or changes direction (same as replying in the Slack thread)."""
    _require_api_token(authorization)
    d = _dispatcher()
    with d.Session() as db:
        t = db.get(Task, task_id)
        if t is None or t.parent_id:
            raise HTTPException(404, "no such top-level task")
    _spawn(d.steer(task_id, d.cfg.owner_id, body.text.strip()))
    return {"ok": True}


class DecisionIn(BaseModel):
    approve: bool
    reason: str = ""
    memory_ticks: list[str] = []
    action_hash: str | None = None


@app.post("/api/approvals/{approval_id}", status_code=202)
async def decide(approval_id: str, body: DecisionIn, authorization: str | None = Header(None)):
    """Approve/reject G1 (contract), G2 (plan), G3 (external action, needs action_hash), G4 (delivery)."""
    _require_api_token(authorization)
    d = _dispatcher()
    with d.Session() as db:
        a = db.get(Approval, approval_id)
        if a is None:
            raise HTTPException(404, "no such approval")
        if a.status != "pending" or a.contract_version != db.get(Task, a.task_id).contract_version:
            raise HTTPException(409, "approval is no longer pending")
        if a.gate == "G3" and body.action_hash != a.action_hash:
            raise HTTPException(409, "action_hash does not match the previewed action")
    _spawn(d.on_approval(d.cfg.owner_id, approval_id, body.approve, button_hash=body.action_hash,
                         memory_ticks=body.memory_ticks, reason=body.reason))
    return {"ok": True}


@app.get("/api/approvals")
async def approvals(authorization: str | None = Header(None), status: str = "pending"):
    _require_api_token(authorization)
    d = _dispatcher()
    with d.Session() as db:
        return [_approval_json(a) for a in db.scalars(
            select(Approval).where(Approval.status == status).order_by(Approval.created_at.desc()).limit(100))]


@app.get("/api/tasks/{task_id}")
async def task_detail(task_id: str, authorization: str | None = Header(None)):
    """One task: contract, plan (who does which step), delivery, sub-tasks, status timeline."""
    _require_api_token(authorization)
    d = _dispatcher()
    with d.Session() as db:
        t = db.get(Task, task_id)
        if t is None:
            raise HTTPException(404, "no such task")
        c = {k: v for k, v in (t.contract or {}).items() if not k.startswith("_")}
        timeline = [{"at": e.at.isoformat(), "actor": e.actor, "from": e.detail.get("from"), "to": e.detail.get("to"),
                     "reason": e.detail.get("reason", "")} for e in db.scalars(
            select(AuditEvent).where(AuditEvent.task_id == t.id, AuditEvent.kind == "transition").order_by(AuditEvent.id))]
        kids = [_task_json(k) for k in db.scalars(select(Task).where(Task.parent_id == t.id))]
        return {**_task_json(t, d.live.holder.get(t.id)), "contract": c,
                "plan": [{"step": f"T{i}", "from": h["from"], "to": h["to"], "task_type": h["task_type"],
                          "objective": h["objective"]} for i, h in enumerate(t.plan or [], 1)],
                "delivery": t.delivery, "subtasks": kids, "timeline": timeline,
                "events": [e for e in d.live.events if e["task_id"] == t.id][-200:]}


class CommandIn(BaseModel):
    text: str


@app.post("/api/commands")
async def commands(body: CommandIn, authorization: str | None = Header(None)):
    """Same as Slack /wf: pause-all | pause <emp|dept> | resume <all|emp|dept> | status | gc."""
    _require_api_token(authorization)
    d = _dispatcher()
    return {"text": d.command(d.cfg.owner_id, body.text)}
