"""Server stays up: long work never blocks the event loop, stuck sessions time out, the office never shows a
ghost 'working' desk, and live-office memory stays bounded."""
import asyncio
import time

from tests.test_flow import contract, delivery, msg, plan, writer, GOOD_COPY
from workforce import dispatcher as dmod
from workforce import live as live_mod
from workforce.db import Task


async def test_stuck_agent_session_times_out_and_escalates(make_dispatcher, monkeypatch):
    monkeypatch.setattr(dmod, "AGENT_RUN_TIMEOUT_S", 0.2)
    d, runner, slack = make_dispatcher({})

    async def hang(**kw):
        await asyncio.sleep(30)
    runner.run = hang
    t0 = time.monotonic()
    await d.handle_message(msg("write a launch caption"))
    assert time.monotonic() - t0 < 5                                       # did not wait for the stuck session
    assert any("timed out" in e.detail.get("text", "") for e in _audit(d, "agent_run"))
    assert d.live.presence["sales_lead"]["state"] != "working"


async def test_run_finished_even_when_the_db_write_fails(make_dispatcher, monkeypatch):
    d, _, _ = make_dispatcher({("sales_lead", "contract"): contract("S")})
    real = d.policy.bump

    def broken(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(d.policy, "bump", broken)
    try:
        await d.handle_message(msg("write a launch caption"))
    except RuntimeError:
        pass
    monkeypatch.setattr(d.policy, "bump", real)
    assert not d.live._runs["sales_lead"]                                    # no ghost "working" desk


async def test_slow_checks_do_not_block_the_server(make_dispatcher, monkeypatch):
    """A 1s check runs in a worker thread: a heartbeat keeps ticking while it runs."""
    d, _, _ = make_dispatcher({("sales_lead", "contract"): contract("S"), ("sales_lead", "plan"): plan(),
                               ("sales_writer", "execute"): writer([GOOD_COPY]), ("sales_lead", "deliver"): delivery})
    real = d.harness.verify

    def slow(task_id, pt):
        time.sleep(1.0)
        return real(task_id, pt)
    monkeypatch.setattr(d.harness, "verify", slow)
    beats = []

    async def heartbeat():
        while True:
            beats.append(time.monotonic())
            await asyncio.sleep(0.05)
    hb = asyncio.create_task(heartbeat())
    await d.handle_message(msg("write a launch caption"))
    hb.cancel()
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    assert max(gaps) < 0.5, max(gaps)                                       # loop never froze for the 1s check
    with d.Session() as db:
        assert db.query(Task).one().status == "DELIVERED"


def test_finished_tasks_are_bounded(monkeypatch):
    monkeypatch.setattr(live_mod, "FINISHED_CAP", 3)
    bus = live_mod.LiveBus(["sales_lead"], owner_of=lambda dept: "sales_lead")
    for i in range(10):
        bus.on_transition(f"t{i}", "sales", "ACCEPTED", "CLOSED", "owner", "")
    assert list(bus._finished) == ["t7", "t8", "t9"]


def _audit(d, kind):
    from sqlalchemy import select
    from workforce.db import AuditEvent
    with d.Session() as db:
        return list(db.scalars(select(AuditEvent).where(AuditEvent.kind == kind)))
