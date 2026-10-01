"""Live Office: presence, handoffs and the office API, driven by the same scripted flow as test_flow."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_flow import GOOD_COPY, OWNER, contract, delivery, msg, plan, writer
from workforce import app as app_mod
from workforce.db import Approval
from workforce.live import LiveBus, sse

SCRIPTS = {("sales_lead", "contract"): contract("S"), ("sales_lead", "plan"): plan(),
           ("sales_writer", "execute"): writer([GOOD_COPY]), ("sales_lead", "deliver"): delivery}


def handoffs(d):
    return [(e["data"]["from"], e["data"]["to"], e["data"]["kind"]) for e in d.live.events if e["type"] == "handoff"]


async def test_note_walks_owner_lead_specialist_lead_owner(make_dispatcher):
    d, _, _ = make_dispatcher(SCRIPTS)
    await d.handle_message(msg("write a launch caption"))
    assert handoffs(d) == [("owner", "sales_lead", "request"), ("sales_lead", "sales_writer", "assign"),
                           ("sales_writer", "sales_lead", "return"), ("sales_lead", "fact_checker", "for_factcheck"),
                           ("fact_checker", "sales_lead", "factcheck_result"), ("sales_lead", "verifier", "for_verification"),
                           ("verifier", "sales_lead", "verdict"), ("sales_lead", "owner", "delivery")]
    woke = [e["data"]["employee_id"] for e in d.live.events
            if e["type"] == "employee.state" and e["data"]["state"] == "working"]
    assert woke == ["sales_lead", "sales_lead", "sales_writer", "fact_checker", "verifier"]   # + Proof, Vera (note built in code)
    assert d.live.presence["sales_writer"]["state"] == "sleeping"        # back to sleep after returning
    assert d.live.presence["sales_lead"]["state"] == "waiting_owner"         # G4 on the owner's desk
    assert d.live.presence["sales_job_scout"]["state"] == "sleeping"  # never woken
    task_id = d.live.events[-1]["task_id"]
    assert d.live.holder[task_id] == "owner"
    seqs = [e["seq"] for e in d.live.events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    with d.Session() as db:
        g4 = db.scalar(select(Approval).where(Approval.gate == "G4"))
    await d.on_approval(OWNER, g4.id, True)
    assert d.live.presence["sales_lead"]["state"] == "sleeping"
    assert task_id not in d.live.holder


async def test_medium_task_waits_for_owner_then_resumes(make_dispatcher):
    d, _, _ = make_dispatcher({("sales_lead", "contract"): contract("M")})
    await d.handle_message(msg("write a launch caption"))
    assert d.live.presence["sales_lead"]["state"] == "waiting_owner"
    assert handoffs(d)[-1] == ("sales_lead", "owner", "approval_request")
    req = [e for e in d.live.events if e["type"] == "approval.requested"]
    assert req and req[0]["data"]["gate"] == "G1"


async def test_pause_shows_on_every_desk(make_dispatcher):
    d, _, _ = make_dispatcher({})
    d.command(OWNER, "pause sales")
    assert d.live.presence["sales_writer"]["state"] == "paused"
    assert d.live.presence["ops_lead"]["state"] == "sleeping"
    d.command(OWNER, "resume sales")
    assert d.live.presence["sales_writer"]["state"] == "sleeping"


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
    d, _, _ = make_dispatcher({("sales_lead", "contract"): contract("M")})
    app_mod.app.state.dispatcher = d
    yield TestClient(app_mod.app), d
    del app_mod.app.state.dispatcher


H = {"Authorization": "Bearer tok"}


def test_office_layout(client):
    c, _ = client
    assert c.get("/api/office").status_code == 401
    o = c.get("/api/office", headers=H).json()
    assert [x["id"] for x in o["departments"]] == ["studio", "sales", "engineering", "ops"]
    assert o["core"]["office_architect"]["name"] == "Mason"            # recruiting sits in Head Office with Atlas
    assert o["core"]["chief_of_staff"]["promptable"] and o["departments"][0]["lead"]["promptable"]
    assert not any(s["promptable"] for x in o["departments"] for s in x["specialists"])


def test_prompt_desk_and_approve(client):
    c, d = client
    assert c.post("/api/desks/sales_writer/prompt", json={"text": "hi"}, headers=H).status_code == 403
    assert c.post("/api/desks/nobody/prompt", json={"text": "hi"}, headers=H).status_code == 404
    r = c.post("/api/desks/sales_lead/prompt", json={"text": "write a launch caption"}, headers=H)
    assert r.status_code == 202
    tid = r.json()["task_id"]
    s = c.get("/api/office/state", headers=H).json()
    assert s["presence"]["sales_lead"]["state"] == "waiting_owner"
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


async def test_delivery_offers_memory_ticks_in_the_office(make_dispatcher):
    d, _, _ = make_dispatcher(SCRIPTS)
    await d.handle_message(msg("write a launch caption"))
    g4 = [e for e in d.live.events if e["type"] == "approval.requested" and e["data"]["gate"] == "G4"][0]["data"]
    assert g4["artifacts"] and g4["memory_candidates"], g4


def test_snapshot_approvals_read_like_events(client):
    c, d = client
    tid = c.post("/api/desks/sales_lead/prompt", json={"text": "write a launch caption"}, headers=H).json()["task_id"]
    a = c.get("/api/office/state", headers=H).json()["pending_approvals"][0]
    assert a["task_id"] == tid and a["title"] == "Contract" and "Objective" in a["summary"]


def test_memory_inspector_shows_each_block_and_forgets(client):
    c, d = client
    from workforce.db import MemoryEntry
    with d.Session() as db:
        db.add_all([MemoryEntry(id="mj", layer="L3", scope_id="studio_poster@jai", kind="feedback", source="t",
                                author="x", status="active", content="Jai reels open on a hard cut"),
                    MemoryEntry(id="ms", layer="L3", scope_id="studio_poster@sherlock", kind="feedback", source="t",
                                author="x", status="active", content="Sherlock ends on the verdict"),
                    MemoryEntry(id="mo", layer="L3", scope_id="show_jai_builder", kind="feedback", source="t",
                                author="x", status="active", content="not Post's")])
        db.commit()
    assert c.get("/api/memory/studio_poster").status_code == 401
    r = c.get("/api/memory/studio_poster", headers=H).json()
    assert [b["scope"] for b in r["blocks"]] == ["studio_poster@jai", "studio_poster@sherlock"]   # shared Post: one block per show
    assert r["budget_chars"] == 3000
    assert c.delete("/api/memory/entry/mj", headers=H).json() == {"ok": True}
    r = c.get("/api/memory/studio_poster", headers=H).json()
    assert [b["scope"] for b in r["blocks"]] == ["studio_poster@sherlock"]
