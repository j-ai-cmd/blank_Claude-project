from workforce.db import Approval, Task
from workforce.policy import ALLOW, APPROVAL, DENY, Policy, action_hash


def _task(db, tid="task_1", version=1):
    t = Task(id=tid, department="sales", requested_by="U_OWNER", original_request="x",
             contract={"objective": "x", "acceptance_criteria": []}, contract_version=version)
    db.add(t)
    db.flush()
    return t


def test_unknown_forbidden_and_allowlist(cfg, Session):
    p, quill = Policy(cfg), cfg.employee("sales_script_writer")
    with Session() as db:
        t = _task(db)
        assert p.check(db, quill, "config.modify", {}, t).outcome == DENY
        assert p.check(db, quill, "made.up", {}, t).outcome == DENY
        assert p.check(db, quill, "crm.read", {}, t).outcome == DENY          # not in allowlist
        assert p.check(db, quill, "workspace.write", {}, t).outcome == ALLOW


def test_three_violations_auto_pause(cfg, Session):
    p, quill = Policy(cfg), cfg.employee("sales_script_writer")
    with Session() as db:
        t = _task(db)
        for _ in range(3):
            p.check(db, quill, "permissions.modify", {}, t)
        d = p.check(db, quill, "workspace.write", {}, t)
        assert d.outcome == DENY and "paused" in d.reason


def test_restricted_kind(cfg, Session):
    p = Policy(cfg)
    with Session() as db:
        t = _task(db)
        # librarian-only action is not grantable to others even if listed
        assert p.check(db, cfg.employee("sales_lead"), "memory.write_shared_service", {}, t).outcome == DENY


def test_private_data_holder_cannot_fetch_and_url_guards(cfg, Session):
    p = Policy(cfg)
    with Session() as db:
        t = _task(db)
        intel = cfg.employee("sales_researcher")
        assert p.check(db, intel, "web.fetch", {"url": "https://example.com/about"}, t).outcome == ALLOW
        assert p.check(db, intel, "web.fetch", {"url": "https://example.com/?q=" + "a" * 300}, t).outcome == DENY
        assert p.check(db, intel, "web.fetch", {"url": "http://127.0.0.1/x"}, t).outcome == DENY
        assert p.check(db, intel, "web.fetch", {"url": "http://localhost:8080"}, t).outcome == DENY
        t.contract = {**t.contract, "_private_strings": ["acme-secret-deal"]}
        assert p.check(db, intel, "web.fetch", {"url": "https://evil.io/acme-secret-deal"}, t).outcome == DENY


def test_verifier_fetch_only_from_log(cfg, Session):
    from workforce.db import AuditEvent
    p, vera = Policy(cfg), cfg.employee("verifier")
    with Session() as db:
        t = _task(db)
        assert p.check(db, vera, "web.fetch", {"url": "https://a.com/x"}, t).outcome == DENY
        db.add(AuditEvent(task_id=t.id, actor="sales_researcher", kind="fetched", detail={"url": "https://a.com/x"}))
        db.flush()
        assert p.check(db, vera, "web.fetch", {"url": "https://a.com/x"}, t).outcome == ALLOW


def test_bulk_split_across_tasks_hits_daily_limit(cfg, Session):
    p, ledger = Policy(cfg), cfg.employee("ops_bookkeeper")
    with Session() as db:
        outcomes = []
        for i in range(3):
            t = _task(db, f"task_{i}")
            outcomes.append(p.check(db, ledger, "drive.create_draft", {"count": 24}, t).outcome)
        assert outcomes[:2] == [ALLOW, ALLOW]
        assert outcomes[2] == APPROVAL  # 72 files > daily 60 even though each task < 25


def test_approval_is_hash_bound_and_single_use(cfg, Session):
    p, echo = Policy(cfg), cfg.employee("sales_outreach_writer")
    with Session() as db:
        t = _task(db)
        params = {"text": "Launch day!", "platform": "email_subject"}
        assert p.check(db, echo, "email.send_external", params, t).outcome == APPROVAL
        a = Approval(id="apr_1", task_id=t.id, gate="G3", tier="R2", action="email.send_external",
                     action_hash=action_hash("email.send_external", params), contract_version=1, status="approved")
        db.add(a)
        db.flush()
        other = {"text": "Different text", "platform": "email_subject", "approval_id": "apr_1"}
        assert p.check(db, echo, "email.send_external", other, t).outcome == APPROVAL  # hash mismatch
        assert p.check(db, echo, "email.send_external", {**params, "approval_id": "apr_1"}, t).outcome == ALLOW
        assert p.check(db, echo, "email.send_external", {**params, "approval_id": "apr_1"}, t).outcome == APPROVAL  # used


def test_spend_cap_then_runaway_pause(cfg, Session):
    p, reel = Policy(cfg), cfg.employee("studio_faceless_editor")
    cap = p.spend_cap(reel)
    with Session() as db:
        t = _task(db)
        assert p.check(db, reel, "video.render", {"est_cost_usd": cap * 0.9}, t).outcome == ALLOW
        assert p.check(db, reel, "video.render", {"est_cost_usd": cap * 0.2}, t).outcome == APPROVAL
        d = p.check(db, reel, "video.render", {"est_cost_usd": cap * 0.7}, t)
        assert d.outcome == DENY and "runaway" in d.reason


def test_kill_switch(cfg, Session):
    p = Policy(cfg)
    with Session() as db:
        t = _task(db)
        p.pause(db, "all", "test", "U_OWNER")
        assert p.check(db, cfg.employee("sales_script_writer"), "workspace.write", {}, t).outcome == DENY
        p.resume(db, "all", "U_OWNER")
        assert p.check(db, cfg.employee("sales_script_writer"), "workspace.write", {}, t).outcome == ALLOW


def test_requesters_and_approvers(cfg):
    p = Policy(cfg)
    assert p.is_requester(cfg.owner_id, "sales")
    assert not p.is_requester("U_SOMEONE", "sales")
    assert p.can_approve(cfg.owner_id, "R3", "sales")
    assert not p.can_approve("U_SOMEONE", "R2", "sales")
