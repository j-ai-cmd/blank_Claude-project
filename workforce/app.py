"""FastAPI entrypoint: Slack events, interactive buttons, slash commands, and the Live Office API."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .agents import FakeRunner, SDKRunner
from . import states
from .config import get_config
from .db import Approval, AuditEvent, MemoryEntry, Pause, Task, make_sessionmaker
from .dispatcher import Dispatcher, _month
from .live import sse
from .slack import SlackClient, parse_event, verify_signature

_background: set[asyncio.Task] = set()
SWEEP_EVERY_S = int(os.environ.get("WORKFORCE_SWEEP_SECONDS", "900"))
DIGEST_HOUR_UTC = int(os.environ.get("WORKFORCE_DIGEST_HOUR_UTC", "3"))   # 03:00 UTC ≈ 08:30 IST


@asynccontextmanager
async def lifespan(_app):
    """Boot recovery + periodic sweep: reminders, parking, stalled/interrupted tasks, budget resume, weekly GC."""
    d = _dispatcher()
    rep = d.sweep(boot=True)
    for tid in rep.get("resume", []):      # restart: re-run each interrupted round once, automatically
        _spawn(d.execute(tid))
    if rep.get("overflow"):                 # the weekly cleanup can run at boot: its report still reaches Atlas
        _spawn(d.report_overflow(rep["overflow"]))

    async def loop():
        ticks = 0
        while True:
            await asyncio.sleep(60)
            ticks += 1
            try:
                for name in d.due_routines():          # e.g. the 9am inbox scan, in your time zone
                    _spawn(d.run_routine(name))
                if ticks * 60 >= SWEEP_EVERY_S:
                    ticks = 0
                    rep = d.sweep()
                    if rep.get("overflow"):
                        await d.report_overflow(rep["overflow"])   # Lex -> Atlas
                    await d.drain_queue()
                    if datetime.now(timezone.utc).hour == DIGEST_HOUR_UTC:
                        d.digest()
            except Exception as e:  # noqa: BLE001
                print(f"[workforce] sweep failed: {e}")
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(title="AI Workforce Dispatcher", lifespan=lifespan)
if os.environ.get("WORKFORCE_FRONTEND_ORIGIN"):
    app.add_middleware(CORSMiddleware, allow_origins=os.environ["WORKFORCE_FRONTEND_ORIGIN"].split(","),
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "Last-Event-ID"])


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
                       x_slack_signature: str | None = Header(None)):
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


@app.post("/api/uploads/{scope}", status_code=201)
async def upload(scope: str, request: Request, name: str = Query(...), authorization: str | None = Header(None)):
    """Add a file as you go: raw body, ?name=<file>. Scopes: profile, finance, general, show-<show>, lane-<lane>."""
    _require_api_token(authorization)
    from . import uploads
    d = _dispatcher()
    if not uploads.valid_scope(d.cfg, scope):
        raise HTTPException(404, "unknown scope")
    try:
        p = uploads.save(d.cfg, scope, name, await request.body())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"scope": scope, "name": p.name, "bytes": p.stat().st_size}


@app.get("/api/uploads")
async def list_uploads(authorization: str | None = Header(None)):
    _require_api_token(authorization)
    from . import uploads
    d = _dispatcher()
    scopes = ["profile", "finance", "general"] + [f"{v['kind']}-{k}" for k, v in d.cfg.shows.items()]
    return {s: uploads.listing(s) for s in scopes}


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


def _approval_json(a: Approval, db=None) -> dict:
    """Same shape as the approval.requested event, so the inbox reads the same after a page reload."""
    p = dict(a.preview or {})
    title, summary = {"G1": "Contract", "G2": "Plan", "G3": a.action or "Action", "G4": "Accept delivery?",
                      "GM": "Save as a standing rule?"}.get(a.gate, a.gate), ""
    t = db.get(Task, a.task_id) if db is not None else None
    if a.gate == "G1" and p.get("contract"):
        c = p["contract"]
        summary = f"Objective: {c.get('objective', '')}\n" + "\n".join(
            f"{x.get('id')}. {x.get('text')}" for x in c.get("acceptance_criteria", []))
    elif a.gate == "G2" and p.get("plan"):
        summary = "\n".join(f"{i}. {h.get('to')}: {h.get('objective')}" for i, h in enumerate(p["plan"], 1))
    elif a.gate == "G3":
        summary = json.dumps(p.get("params") or {}, indent=1)[:1500]
        if a.status == "confirming":
            title, summary = f"CONFIRM {a.action}", "Irreversible (R3). Approve again to confirm.\n" + summary
    elif a.gate == "G4" and t is not None:
        summary = (t.delivery or {}).get("note", "")
        p["memory_candidates"] = [{"id": m.id, "text": m.content} for m in db.scalars(select(MemoryEntry).where(
            MemoryEntry.task_id == t.id, MemoryEntry.status == "candidate", MemoryEntry.standing.is_(False)))]
    elif a.gate == "GM" and db is not None and p.get("memory_id"):
        m = db.get(MemoryEntry, p["memory_id"])
        summary = m.content if m else ""
    return {"id": a.id, "task_id": a.task_id, "gate": a.gate, "tier": a.tier, "action": a.action,
            "action_hash": a.action_hash, "contract_version": a.contract_version, "status": a.status,
            "employee_id": p.get("employee"), "title": title, "summary": summary[:1500], "preview": p,
            "created_at": a.created_at.isoformat()}


@app.get("/api/office")
async def office(authorization: str | None = Header(None)):
    """Static floor plan: every department, who sits where, who can be prompted. Rarely changes."""
    _require_api_token(authorization)
    d = _dispatcher()
    cfg = d.cfg
    depts = []
    core = {k: _employee_json(d, cfg.employee(k)) for k in cfg.org["core"]}
    for key, raw in cfg.org["departments"].items():
        if key not in cfg.leads:   # the lead-less office desk (Mason) sits in Head Office, next to Atlas
            core.update({e.id: {**_employee_json(d, e), "department": "hq"} for e in cfg.specialists_of(key)})
            continue
        depts.append({"id": key, "channel": raw["channel"], "lead": _employee_json(d, cfg.employee(cfg.leads[key])),
                      "specialists": [_employee_json(d, e) for e in cfg.specialists_of(key)]})
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
        approvals = [_approval_json(a, db) for a in db.scalars(select(Approval).where(Approval.status.in_(["pending", "confirming"])))]
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
    # On a reconnect the browser resends the same URL; Last-Event-ID is newer than ?since, so it wins.
    start = int(last_event_id) if (last_event_id or "").isdigit() else since
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
        dept, channel, thread = d.office_target(employee_id)
    except ValueError as e:
        raise HTTPException(403, str(e))
    created: asyncio.Future = asyncio.get_running_loop().create_future()

    async def run():
        try:
            await d.start_task(dept, d.cfg.owner_id, body.text.strip(), channel, thread,
                               on_created=lambda tid: created.done() or created.set_result(tid))
        except Exception as e:  # noqa: BLE001 — surface a failure before the task exists instead of hanging
            if not created.done():
                created.set_exception(e)
            raise
    _spawn(run())
    try:
        return {"task_id": await asyncio.wait_for(created, timeout=30)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"couldn't create the task: {e}")


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
        if a.status not in ("pending", "confirming") or (
                a.gate != "GM" and a.contract_version != db.get(Task, a.task_id).contract_version):
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
        return [_approval_json(a, db) for a in db.scalars(
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


# ====================================================================== memory inspector (yours only)
@app.get("/api/memory/{employee_id}")
async def memory_of(employee_id: str, authorization: str | None = Header(None)):
    """Exactly what one employee remembers: its own memory block, and for a shared employee one block per show.
    Grok Bot has no memory inspector; here you can read every line and delete any of it."""
    _require_api_token(authorization)
    d = _dispatcher()
    if employee_id not in d.cfg.employees:
        raise HTTPException(404, "no such employee")
    budget = int(d.cfg.memory["layers"]["L3_employee_private"].get("max_chars", 3000))
    with d.Session() as db:   # exact match in Python: '_' in an id would be a LIKE wildcard
        rows = [m for m in db.scalars(select(MemoryEntry).where(MemoryEntry.layer == "L3",
                                                                 MemoryEntry.status.in_(["active", "stale"])))
                if m.scope_id == employee_id or m.scope_id.startswith(f"{employee_id}@")]
    blocks: dict[str, list] = {}
    for m in rows:
        blocks.setdefault(m.scope_id, []).append({"id": m.id, "text": m.content, "kind": m.kind, "pinned": m.pinned,
                                                  "standing": m.standing, "source": m.pointer or m.source})
    return {"employee": employee_id, "budget_chars": budget,
            "blocks": [{"scope": k, "chars": sum(len(x["text"]) for x in v), "entries": v} for k, v in sorted(blocks.items())]}


@app.delete("/api/memory/entry/{entry_id}")
async def forget(entry_id: str, authorization: str | None = Header(None)):
    """You remove one memory. It is archived (kept in the audit trail), never shown to any employee again."""
    _require_api_token(authorization)
    d = _dispatcher()
    with d.Session() as db:
        m = db.get(MemoryEntry, entry_id)
        if m is None:
            raise HTTPException(404, "no such memory")
        m.status = "archived"
        db.add(AuditEvent(task_id=m.task_id, actor=d.cfg.owner_id, kind="memory_forgotten", detail={"id": m.id}))
        db.commit()
    return {"ok": True}


class CommandIn(BaseModel):
    text: str


@app.post("/api/commands")
async def commands(body: CommandIn, authorization: str | None = Header(None)):
    """Same as Slack /wf: pause-all | pause <emp|dept> | resume <all|emp|dept> | status | gc."""
    _require_api_token(authorization)
    d = _dispatcher()
    return {"text": d.command(d.cfg.owner_id, body.text)}
