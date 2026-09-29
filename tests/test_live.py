"""Live Office: presence, handoffs and the office API, driven by the same scripted flow as test_flow."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from test_flow import GOOD_COPY, OWNER, contract, delivery, msg, plan, writer
from workforce import app as app_mod
from workforce.db import Approval
from workforce.live import LiveBus, sse

SCRIPTS = {("mkt_lead", "contract"): contract("S"), ("mkt_lead", "plan"): plan(),
           ("mkt_copywriter", "execute"): writer([GOOD_COPY]), ("mkt_lead", "deliver"): delivery}


def handoffs(d):
    return [(e["data"]["from"], e["data"]["to"], e["data"]["kind"]) for e in d.live.events if e["type"] == "handoff"]


async def test_note_walks_owner_lead_specialist_lead_owner(make_dispatcher):
    d, _, _ = make_dispatcher(SCRIPTS)
    await d.handle_message(msg("write a launch caption"))
    assert handoffs(d) == [("owner", "mkt_lead", "request"), ("mkt_lead", "mkt_copywriter", "assign"),
                           ("mkt_copywriter", "mkt_lead", "return"), ("mkt_lead", "owner", "delivery")]
    woke = [e["data"]["employee_id"] for e in d.live.events
            if e["type"] == "employee.state" and e["data"]["state"] == "working"]
    assert woke == ["mkt_lead", "mkt_lead", "mkt_copywriter", "mkt_lead"]   # contract, plan, execute, deliver
    assert d.live.presence["mkt_copywriter"]["state"] == "sleeping"        # back to sleep after returning
    assert d.live.presence["mkt_lead"]["state"] == "waiting_owner"         # G4 on the owner's desk
    assert d.live.presence["mkt_graphic_designer"]["state"] == "sleeping"  # never woken
    task_id = d.live.events[-1]["task_id"]
    assert d.live.holder[task_id] == "owner"
    seqs = [e["seq"] for e in d.live.events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    with d.Session() as db:
        g4 = db.scalar(select(Approval).where(Approval.gate == "G4"))
    await d.on_approval(OWNER, g4.id, True)
    assert d.live.presence["mkt_lead"]["state"] == "sleeping"
    assert task_id not in d.live.holder


async def test_medium_task_waits_for_owner_then_resumes(make_dispatcher):
    d, _, _ = make_dispatcher({("mkt_lead", "contract"): contract("M")})
    await d.handle_message(msg("write a launch caption"))
    assert d.live.presence["mkt_lead"]["state"] == "waiting_owner"
    assert handoffs(d)[-1] == ("mkt_lead", "owner", "approval_request")
    req = [e for e in d.live.events if e["type"] == "approval.requested"]
    assert req and req[0]["data"]["gate"] == "G1"


async def test_pause_shows_on_every_desk(make_dispatcher):
    d, _, _ = make_dispatcher({})
    d.command(OWNER, "pause marketing")
    assert d.live.presence["mkt_copywriter"]["state"] == "paused"
    assert d.live.presence["sales_lead"]["state"] == "sleeping"
    d.command(OWNER, "resume marketing")
    assert d.live.presence["mkt_copywriter"]["state"] == "sleeping"


async def test_sse_replays_then_streams():
    bus = LiveBus(["a"])
    bus.publish("x")
    bus.publish("y")
    gen = sse(bus, since=1, heartbeat_s=5)
    first = await gen.__anext__()
    assert first.startswith("id: 2\nevent: y\n")
    assert "event: hello" in await gen.__anext__()
    nxt = asyncio.ensure_future(gen.__anext__())
    await asyncio.sleep(0)
    bus.publish("z")
    assert json.loads((await nxt).split("data: ")[1])["type"] == "z"
    await gen.aclose()


async def test_sse_resync_when_buffer_lost():
    bus = LiveBus(["a"], buffer=2)
    for _ in range(5):
        bus.publish("x")
    gen = sse(bus, since=0)
    assert "event: resync" in await gen.__anext__()
    await gen.aclose()


@pytest.fixture
def client(monkeypatch, make_dispatcher):
    monkeypatch.setenv("WORKFORCE_API_TOKEN", "tok")
    d, _, _ = make_dispatcher({("mkt_lead", "contract"): contract("M")})
    app_mod.app.state.dispatcher = d
    yield TestClient(app_mod.app), d
    del app_mod.app.state.dispatcher


H = {"Authorization": "Bearer tok"}


def test_office_layout(client):
    c, _ = client
    assert c.get("/api/office").status_code == 401
    o = c.get("/api/office", headers=H).json()
    assert [x["id"] for x in o["departments"]] == ["marketing", "sales", "recruiting", "ops"]
    assert o["core"]["chief_of_staff"]["promptable"] and o["departments"][0]["lead"]["promptable"]
    assert not any(s["promptable"] for x in o["departments"] for s in x["specialists"])


def test_prompt_desk_and_approve(client):
    c, d = client
    assert c.post("/api/desks/mkt_copywriter/prompt", json={"text": "hi"}, headers=H).status_code == 403
    assert c.post("/api/desks/nobody/prompt", json={"text": "hi"}, headers=H).status_code == 404
    r = c.post("/api/desks/mkt_lead/prompt", json={"text": "write a launch caption"}, headers=H)
    assert r.status_code == 202
    tid = r.json()["task_id"]
    s = c.get("/api/office/state", headers=H).json()
    assert s["presence"]["mkt_lead"]["state"] == "waiting_owner"
    assert [t["id"] for t in s["open_tasks"]] == [tid] and s["open_tasks"][0]["holder"] == "owner"
    apr = s["pending_approvals"][0]
    assert apr["gate"] == "G1"
    detail = c.get(f"/api/tasks/{tid}", headers=H).json()
    assert detail["status"] == "CONTRACT_DRAFTED" and detail["timeline"]
    assert c.post(f"/api/approvals/{apr['id']}", json={"approve": False}, headers=H).status_code == 202
    assert c.post(f"/api/approvals/{apr['id']}", json={"approve": False}, headers=H).status_code == 409
    assert c.get(f"/api/tasks/{tid}", headers=H).json()["status"] == "CANCELLED"


def test_live_requires_token(client):
    c, _ = client
    assert c.get("/api/live").status_code == 401
