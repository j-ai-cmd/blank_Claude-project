import pytest

from workforce import harness as harness_mod
from workforce.agents import FakeRunner
from workforce.config import Config
from workforce.db import make_sessionmaker
from workforce.dispatcher import Dispatcher
from workforce.slack import SlackClient


@pytest.fixture(scope="session")
def cfg():
    return Config()


@pytest.fixture
def Session(tmp_path):
    return make_sessionmaker(f"sqlite:///{tmp_path}/t.db")


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(harness_mod, "WORKSPACE_ROOT", tmp_path / "ws")
    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    for k in ("SMTP_HOST", "IMAP_HOST", "WORKFORCE_CONNECTORS", "RUNTIME_BACKEND", "VOICE_DEV_ENGINE"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path / "ws"


@pytest.fixture
def make_dispatcher(cfg, Session):
    runners = []

    async def proof_pass(tools, ctx):   # Proof finds no factual claims unless a test scripts it
        r = await tools["submit_factcheck"].handler({"claims": []})
        assert not r.get("is_error"), r

    made = []

    def _make(scripts):
        runner = FakeRunner({("fact_checker", "factcheck"): proof_pass, **scripts})
        runners.append(runner)
        slack = SlackClient(token="")
        d = Dispatcher(cfg, Session, runner, slack)
        made.append(d)
        return d, runner, slack
    yield _make
    for r in runners:  # a failing assertion inside a scripted agent must fail the test
        assert not r.script_errors, "\n".join(r.script_errors)
    for d in made:  # the Live Office must mirror the database after every flow
        problems = live_problems(d)
        assert not problems, "Live Office out of sync:\n" + "\n".join(problems)


def live_problems(d) -> list[str]:
    from sqlalchemy import select
    from workforce import states
    from workforce.db import Approval, Task
    bus, out = d.live, []
    with d.Session() as db:
        pending = list(db.scalars(select(Approval).where(Approval.status.in_(["pending", "confirming"]))))
        tasks = list(db.scalars(select(Task)))
    asked = {e["data"].get("approval_id") for e in bus.events if e["type"] == "approval.requested"}
    seen = {e["task_id"] for e in bus.events if e["type"] == "task.created"}   # tests may insert rows directly
    last = {e["task_id"]: e["data"]["to"] for e in bus.events if e["type"] == "task.status"}
    tasks = [t for t in tasks if t.id in seen and last.get(t.id, t.status) == t.status]   # skip rows a test edited by hand
    pending = [a for a in pending if a.task_id in seen]
    for a in pending:
        if a.id not in asked:
            out.append(f"pending {a.gate} approval {a.id} never reached the inbox")
    for emp, runs in bus._runs.items():
        if runs:
            out.append(f"{emp} still shown working on {runs}")
    for t in tasks:
        h = bus.holder.get(t.id)
        if t.status in states.TERMINAL and h:
            out.append(f"{t.id} is {t.status} but its note is still with {h}")
        if t.status not in states.TERMINAL and not h:
            out.append(f"{t.id} is {t.status} but nobody holds its note")
        if t.status == "DELIVERED" and h != "owner":
            out.append(f"{t.id} delivered but the note is with {h}, not the owner")
    return out


@pytest.fixture
def runtimes(monkeypatch):
    """Pretend the Modal render + code sandboxes are configured (routes that need them are otherwise refused)."""
    monkeypatch.setenv("RUNTIME_BACKEND", "local")


@pytest.fixture
def render_stub(cfg, monkeypatch, runtimes):
    """Video/image checks need the Modal render sandbox (not built). Tests of the WORKFLOW swap them for a
    real, passing check so the flow can be exercised; the checks themselves are tested separately."""
    passing = "python3 -m workforce.checks deliverable_only {T}/primary"
    for cid in ("hyperframes_check", "video_spec", "image_spec", "sandbox_tests"):
        monkeypatch.setitem(cfg.checks["checks"], cid, {**cfg.checks["checks"][cid], "cmd": passing})
