import json
import subprocess
import sys
import time

import pytest

from workforce import states
from workforce.checks import main as check_main
from workforce.db import Approval, MemoryEntry, Task
from workforce.memory import MemoryStore
from workforce.routing import RouteError, resolve
from workforce.slack import parse_event, verify_signature


# ---------------------------------------------------------------- config
def test_config_validator_passes():
    out = subprocess.run([sys.executable, "scripts/validate_config.py"], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout


def test_org_loaded(cfg):
    assert len(cfg.employees) == 22
    assert cfg.leads == {"studio": "studio_lead", "sales": "sales_lead", "engineering": "eng_lead", "ops": "ops_lead"}
    assert "office" in cfg.org["departments"] and "office" not in cfg.leads   # Atlas's lead-less recruiting desk
    assert [e.id for e in cfg.specialists_of("office")] == ["office_architect"]
    assert cfg.dept_channels["#sales"] == "sales"


# ---------------------------------------------------------------- states
def test_hard_transitions(Session):
    with Session() as db:
        t = Task(id="t1", department="sales", requested_by="U", original_request="x", status="PLANNED",
                 contract_version=1)
        db.add(t)
        with pytest.raises(states.TransitionError):
            states.transition(db, t, "IN_PROGRESS", "dispatcher")          # no G1
        with pytest.raises(states.TransitionError):
            states.transition(db, t, "DELIVERED", "dispatcher")            # not reachable
        db.add(Approval(id="a1", task_id="t1", gate="G1", contract_version=1, status="approved"))
        t.g1_approval_id = "a1"
        states.transition(db, t, "IN_PROGRESS", "dispatcher")
        states.transition(db, t, "VERIFYING", "harness")
        with pytest.raises(states.TransitionError):
            states.transition(db, t, "DELIVERED", "x")                     # no verification record
        t.verification_id = "v1"
        states.transition(db, t, "DELIVERED", "lead")
        with pytest.raises(states.TransitionError):
            states.transition(db, t, "ACCEPTED", "agent")                  # humans only


# ---------------------------------------------------------------- routing
def test_routing(cfg, monkeypatch):
    r = resolve(cfg, "sales_writer", "post_copy")
    assert r.skills == ["humanizer"]
    assert {"packet_schema", "criteria_covered", "pii_absent", "spellcheck"} <= set(r.checks)
    with pytest.raises(RouteError):
        resolve(cfg, "sales_writer", "banner_or_ad")
    monkeypatch.delenv("RUNTIME_BACKEND", raising=False)
    with pytest.raises(RouteError, match="isn't set up yet"):     # refused before any credit is spent
        resolve(cfg, "studio_designer", "jai_visual")
    monkeypatch.setenv("RUNTIME_BACKEND", "local")
    r = resolve(cfg, "studio_designer", "football_visual")
    assert r.skills == ["football-video", "ui-ux-pro-max"]
    r = resolve(cfg, "studio_builder", "sherlock_reel")
    assert r.skills == ["sherlock"] and "hyperframes" in r.support


# ---------------------------------------------------------------- memory
def test_memory_acl_and_promotion(cfg, Session):
    ms = MemoryStore(cfg)
    pixel, reel = cfg.employee("studio_designer"), cfg.employee("studio_builder")
    with Session() as db:
        t = Task(id="t1", department="sales", requested_by="U", original_request="x", status="ACCEPTED")
        db.add(t)
        good = ms.submit_candidate(db, pixel, t, "Owner prefers the dark background variant")
        intent = ms.submit_candidate(db, pixel, t, "I will use blue next time")
        pii = ms.submit_candidate(db, pixel, t, "Contact is jane@acme-corp.com")
        unticked = ms.submit_candidate(db, pixel, t, "Owner likes serif fonts")
        db.flush()
        assert ms.promote(db, good.id, t, owner_ticked=True).status == "active"
        assert ms.promote(db, intent.id, t, owner_ticked=True).status == "rejected"
        assert ms.promote(db, pii.id, t, owner_ticked=True).status == "rejected"
        assert ms.promote(db, unticked.id, t, owner_ticked=False).status == "rejected"
        assert [m.id for m in ms.read(db, pixel, "background")] == [good.id]
        assert ms.read(db, reel, "background") == []          # isolation: Frame can't read Pixel's L3


def test_memory_gc_keeps_pinned(cfg, Session):
    from datetime import datetime, timedelta, timezone
    ms = MemoryStore(cfg)
    old = datetime.now(timezone.utc) - timedelta(days=90)
    with Session() as db:
        db.add(MemoryEntry(id="m1", layer="L1", scope_id="sales", kind="decision", content="a", source="s",
                           author="x", status="active", created_at=old))
        db.add(MemoryEntry(id="m2", layer="L1", scope_id="sales", kind="decision", content="b", source="s",
                           author="x", status="active", created_at=old, pinned=True))
        db.flush()
        ms.gc(db)
        assert db.get(MemoryEntry, "m1").status == "archived"
        assert db.get(MemoryEntry, "m2").status == "active"


# ---------------------------------------------------------------- slack
def test_slack_signature():
    import hashlib
    import hmac
    body, ts = b'{"a":1}', str(int(time.time()))
    sig = "v0=" + hmac.new(b"secret", f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    assert verify_signature("secret", ts, body, sig)
    assert not verify_signature("secret", ts, body + b"x", sig)
    assert not verify_signature("secret", str(int(time.time()) - 1000), body, sig)


def test_slack_filters_bots_and_subtypes():
    human = {"event_id": "E1", "event": {"type": "message", "user": "U1", "text": "hi", "channel": "C1", "ts": "1"}}
    assert parse_event(human).user == "U1"
    assert parse_event({"event": {**human["event"], "bot_id": "B1"}}) is None
    assert parse_event({"event": {**human["event"], "subtype": "bot_message"}}) is None
    assert parse_event({"event": {**human["event"], "subtype": "message_changed"}}) is None


# ---------------------------------------------------------------- checks
def test_checks(tmp_path, capsys):
    good = tmp_path / "copy.md"
    good.write_text("Our new planner helps small teams finish work sooner.")
    assert check_main(["no_ai_tells", str(good)]) == 0
    slop = tmp_path / "slop.md"
    slop.write_text("Let's delve into this tapestry. It's a game-changer that will elevate your seamless workflow.")
    assert check_main(["no_ai_tells", str(slop)]) == 1
    assert check_main(["char_limits", str(good), "x"]) == 0
    pii = tmp_path / "a"
    pii.mkdir()
    (pii / "x.txt").write_text("email me at bob@corp.com")
    assert check_main(["pii_absent", str(pii)]) == 1
    assert check_main(["spellcheck", str(good)]) == 0
    bad = tmp_path / "bad.md"
    bad.write_text("TODO write the the copy")
    assert check_main(["spellcheck", str(bad)]) == 1
    h, r = tmp_path / "h.json", tmp_path / "r.json"
    h.write_text(json.dumps({"criteria": ["1", "2"]}))
    r.write_text(json.dumps({"task_id": "t", "from": "x", "status": "done", "outputs": [], "confidence": 0.9,
                             "self_check": [{"criterion_id": "1", "result": "met", "evidence": "ok"}]}))
    assert check_main(["criteria_covered", str(h), str(r)]) == 1
    assert check_main(["packet_schema", str(r)]) == 0
    assert check_main(["video_spec", str(good), "{}"]) in (1, 3)


def test_private_data_holders_never_get_webfetch(cfg):
    from workforce.dispatcher import BUILTINS
    for e in cfg.employees.values():
        builtins = {n for n, a in BUILTINS.items() if a in e.tools}
        if set(e.tools) & cfg.private_data_tools and "web.fetch" not in e.tool_constraints:
            assert "WebFetch" not in builtins, e.id

