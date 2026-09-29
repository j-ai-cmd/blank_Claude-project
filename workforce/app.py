"""FastAPI entrypoint: Slack events, interactive buttons, slash commands, and a read-only API."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select

from .agents import FakeRunner, SDKRunner
from .config import get_config
from .db import Task, make_sessionmaker
from .dispatcher import Dispatcher
from .slack import SlackClient, parse_event, verify_signature

_background: set[asyncio.Task] = set()
SWEEP_EVERY_S = int(os.environ.get("WORKFORCE_SWEEP_SECONDS", "900"))


@asynccontextmanager
async def lifespan(_app):
    """Boot recovery + periodic sweep: reminders, parking, stalled/interrupted tasks, budget resume, weekly GC."""
    d = _dispatcher()
    d.sweep(boot=True)

    async def loop():
        while True:
            await asyncio.sleep(SWEEP_EVERY_S)
            try:
                d.sweep()
            except Exception as e:  # noqa: BLE001
                print(f"[workforce] sweep failed: {e}")
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(title="AI Workforce Dispatcher", lifespan=lifespan)


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


def _require_api_token(authorization: str | None) -> None:
    token = os.environ.get("WORKFORCE_API_TOKEN")
    if not token or authorization != f"Bearer {token}":
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
