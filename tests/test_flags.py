"""One test (at least) per flag in docs/FLAGS-CODE.md."""
import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from workforce import harness as hmod
from workforce.agents import ToolSpec, ok
from workforce.checks import main as check_main
from workforce.db import Approval, AuditEvent, MemoryEntry, Pause, Task
from workforce.dispatcher import validate_contract, validate_pending_actions
from workforce.policy import Policy
from workforce.slack import InboundMessage

OWNER = "U_OWNER"
COPY = "Our new planner helps small teams finish work sooner."
POST = "Small teams can now plan their week in one place."


def msg(text, eid="E1", thread=None, channel="#sales"):
    return InboundMessage(event_id=eid, user=OWNER, channel="C1", channel_name=channel, text=text,
                          ts="100.1", thread_ts=thread, is_dm=False)


def ref_of(saved):
    return saved["content"][0]["text"].removeprefix("saved ")


def two_step_contract(size="M"):
    async def fn(tools, ctx):
        r = await tools["submit_contract"].handler({
            "objective": "Research a client, then pitch them", "size": size,
            "deliverables": [
                {"id": "D1", "description": "brief", "format": "md", "assignee": "sales_ideas", "task_type": "generate_ideas"},
                {"id": "D2", "description": "pitch", "format": "md", "assignee": "sales_writer", "task_type": "pitch_email"}],
            "acceptance_criteria": [{"id": "1", "text": "post_copy", "check": "automatic"},
                                    {"id": "2", "text": "post", "check": "automatic"}]})
        assert not r.get("is_error"), r
    return fn


async def two_step_plan(tools, ctx):
    r = await tools["submit_plan"].handler({"handoffs": [
        {"deliverable": "D1", "to": "sales_ideas", "task_type": "generate_ideas", "objective": "brief", "criteria": ["1"]},
        {"deliverable": "D2", "to": "sales_writer", "task_type": "pitch_email", "objective": "pitch",
         "criteria": ["2"], "inputs_from": ["T1"], "platform": "x"}]})
    assert not r.get("is_error"), r


def writer(text, criteria=("1",), extra=None):
    async def fn(tools, ctx):
        ref = ref_of(await tools["workspace_write"].handler({"name": "out.md", "content": text}))
        r = await tools["submit_return"].handler({
            "status": "done", "outputs": [ref], "confidence": 0.9, "summary": "wrote it",
            "self_check": [{"criterion_id": c, "result": "met", "evidence": "checked"} for c in criteria],
            **(extra or {})})
        assert not r.get("is_error"), r
    return fn


def poster(seen):
    async def fn(tools, ctx):
        upstream = re.findall(r"artifact://\S+?T1-out\.md", ctx["prompt"])
        assert upstream, "T2 must be told T1's real output ref (C2)"
        got = await tools["workspace_read"].handler({"ref": upstream[0]})
        seen["upstream"] = got["content"][0]["text"]
        denied = await tools["workspace_read"].handler({"ref": "artifact://x/T9-secret.md"})
        seen["denied"] = denied.get("is_error")
        ref = ref_of(await tools["workspace_write"].handler({"name": "out.md", "content": POST}))
        r = await tools["submit_return"].handler({
            "status": "done", "outputs": [ref], "confidence": 0.9, "summary": "posted",
            "self_check": [{"criterion_id": "2", "result": "met", "evidence": "used T1"}],
            "memory_candidates": [{"content": "Owner likes one-line posts"}]})
        assert not r.get("is_error"), r
    return fn


async def delivery(tools, ctx):
    assert "wrote it" in ctx["prompt"] and "posted" in ctx["prompt"], "lead must see real summaries (C12)"
    await tools["submit_delivery"].handler({"note": "Done."})


def verdict(results, ids=("1", "2")):
    calls = {"i": 0}

    async def fn(tools, ctx):
        res = results[min(calls["i"], len(results) - 1)]
        calls["i"] += 1
        await tools["submit_verdict"].handler({"grades": [{"criterion_id": c, "result": res, "evidence": "e"} for c in ids]})
    return fn


def task(d):
    with d.Session() as db:
        return db.scalars(select(Task).where(Task.parent_id.is_(None))).first()


async def approve(d, gate):
    with d.Session() as db:
        a = db.scalar(select(Approval).where(Approval.gate == gate, Approval.status == "pending"))
    return await d.on_approval(OWNER, a.id, True)


# ---------------------------------------------------------------- C1 C2 C3 C12 C13
async def test_work_flows_between_specialists(make_dispatcher):
    seen = {}
    d, runner, slack = make_dispatcher({
        ("sales_lead", "contract"): two_step_contract(), ("sales_lead", "plan"): two_step_plan,
        ("sales_ideas", "execute"): writer(COPY), ("sales_writer", "execute"): poster(seen),
        ("verifier", "verify"): verdict(["PASS"]), ("sales_lead", "deliver"): delivery})
    await d.handle_message(msg("caption and a post, verify it"))
    await approve(d, "G1")
    t = task(d)
    assert t.status == "DELIVERED", t.status
    assert COPY in seen["upstream"]                       # C2 T2 received T1's output
    assert seen["denied"]                                 # C2 can't read what isn't upstream
    arts = sorted(p.name for p in (hmod.task_dir(t.id) / "artifacts").glob("*"))
    assert arts == ["T1-out.md", "T2-out.md"]             # C3 no overwrite despite same name
    with d.Session() as db:
        kinds = {(e.actor, e.detail.get("action")) for e in db.scalars(select(AuditEvent).where(AuditEvent.kind == "tool_check"))}
        cand = db.scalar(select(MemoryEntry).where(MemoryEntry.author == "sales_writer"))
    assert ("sales_ideas", "workspace.write") in kinds and ("sales_lead", "submit_plan") in kinds  # C1
    assert cand.derived_from_untrusted                    # C13 read another employee's output
    texts = " ".join(str(m) for m in slack.sent)
    assert "T1-out.md" in texts and "Verifier:" in texts  # C12 artifacts posted + grades on G4


async def test_guard_blocks_restricted_and_paused(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({})
    with d.Session() as db:
        db.add(Task(id="tx", department="sales", requested_by=OWNER, original_request="x", contract_version=1))
        db.commit()

    async def h(args):
        return ok("ran")
    quill = cfg.employee("sales_writer")
    r = await d._guard(quill, "tx", ToolSpec("submit_plan", "", {}, h)).handler({})
    assert r.get("is_error") and "denied" in r["content"][0]["text"]            # C1 lead-only tool
    with d.Session() as db:
        d.policy.pause(db, "emp:sales_writer", "t", OWNER)
        db.commit()
    r = await d._guard(quill, "tx", ToolSpec("workspace_write", "", {}, h)).handler({})
    assert r.get("is_error") and "paused" in r["content"][0]["text"]


# ---------------------------------------------------------------- C4 C5 C6 C7
def test_contract_rules(cfg, runtimes):
    lead = cfg.employee("sales_lead")
    base = {"objective": "x", "acceptance_criteria": [{"id": "1", "text": "t", "check": "automatic"}]}
    two = [{"id": "D1", "assignee": "sales_writer", "task_type": "post_copy"},
           {"id": "D2", "assignee": "sales_ideas", "task_type": "generate_ideas"}]
    assert any("at most 1" in p for p in validate_contract({**base, "size": "S", "deliverables": two}, lead, cfg))   # C5
    assert any("assignee" in p for p in validate_contract({**base, "size": "M", "deliverables": [{"id": "D1"}]}, lead, cfg))  # C6
    studio = cfg.employee("studio_lead")
    sher = [{"id": "D1", "assignee": "studio_builder", "task_type": "sherlock_reel"}]
    assert any("no show" in p   # C7 / I1: no show named -> a show's route can't run
               for p in validate_contract({**base, "size": "M", "deliverables": sher}, studio, cfg, "make an ai reel", show=None))
    assert not validate_contract({**base, "size": "M", "deliverables": sher}, studio, cfg, "sherlock, make an ai reel", show="sherlock")


async def test_plan_must_cover_criteria_and_size(make_dispatcher):
    results = {}

    async def partial_plan(tools, ctx):
        r = await tools["submit_plan"].handler({"handoffs": [
            {"deliverable": "D1", "to": "sales_writer", "task_type": "post_copy", "objective": "c", "criteria": ["1"]}]})
        results["missing"] = r["content"][0]["text"]
        r = await tools["submit_plan"].handler({"handoffs": [
            {"deliverable": "D1", "to": "sales_writer", "task_type": "post_copy", "objective": "c", "criteria": ["1", "2"],
             "inputs_from": ["T1"]}]})
        results["self_ref"] = r["content"][0]["text"]
    d, _, _ = make_dispatcher({("sales_lead", "contract"): two_step_contract(), ("sales_lead", "plan"): partial_plan})
    await d.handle_message(msg("please do the task"))
    await approve(d, "G1")
    assert "not assigned to anyone: ['2']" in results["missing"]          # C4
    assert "earlier packets" in results["self_ref"]


async def test_g1_card_shows_assignee_and_skills(make_dispatcher):
    d, _, slack = make_dispatcher({("sales_lead", "contract"): two_step_contract()})
    await d.handle_message(msg("please do the task"))
    card = json.dumps([m for m in slack.sent if m.get("blocks")])
    assert "Spark" in card and "research" in card and "generate_ideas" in card and "Voice" in card   # C6


# ---------------------------------------------------------------- C8
async def test_blocked_specialist_escalates_with_questions(make_dispatcher):
    async def unsure(tools, ctx):
        ref = ref_of(await tools["workspace_write"].handler({"name": "out.md", "content": COPY}))
        await tools["submit_return"].handler({"status": "done", "outputs": [ref], "confidence": 0.3,
                                              "self_check": [], "open_questions": ["Which product name?"]})
    d, runner, slack = make_dispatcher({("sales_lead", "contract"): two_step_contract(), ("sales_lead", "plan"): two_step_plan,
                                        ("sales_ideas", "execute"): unsure})
    await d.handle_message(msg("please do the task"))
    await approve(d, "G1")
    assert task(d).status == "ESCALATED"
    assert [c["phase"] for c in runner.calls].count("execute") == 1        # no blind retries
    assert any("Which product name?" in m.get("text", "") for m in slack.sent)


# ---------------------------------------------------------------- C9
def test_citations_must_be_observed(tmp_path):
    rp, src = tmp_path / "r.json", tmp_path / "sources.json"
    src.write_text(json.dumps({"urls": ["https://a.com/x"], "memory_ids": ["mem_1"], "pointers": []}))
    rp.write_text(json.dumps({"citations": [{"claim": "c", "source": "crm:deal/1"}]}))
    assert check_main(["citations_resolve", str(rp), str(src), str(tmp_path)]) == 1
    rp.write_text(json.dumps({"citations": [{"claim": "c", "source": "https://a.com/x"},
                                            {"claim": "d", "source": "memory:mem_1"}]}))
    assert check_main(["citations_resolve", str(rp), str(src), str(tmp_path)]) == 0


# ---------------------------------------------------------------- C10 C11
async def test_numbers_force_verifier_and_owner_text_trusted(make_dispatcher):
    async def contract_s(tools, ctx):
        assert "<owner_request" in ctx["prompt"] and 'source="owner_request"' not in ctx["prompt"]   # C11
        await tools["submit_contract"].handler({
            "objective": "price line", "size": "S",
            "deliverables": [{"id": "D1", "description": "c", "assignee": "sales_writer", "task_type": "post_copy"}],
            "acceptance_criteria": [{"id": "1", "text": "t", "check": "automatic"}]})

    async def plan_s(tools, ctx):
        await tools["submit_plan"].handler({"handoffs": [
            {"deliverable": "D1", "to": "sales_writer", "task_type": "post_copy", "objective": "c", "criteria": ["1"]}]})
    d, runner, _ = make_dispatcher({("sales_lead", "contract"): contract_s, ("sales_lead", "plan"): plan_s,
                                    ("sales_writer", "execute"): writer("Plans start at $49 a month for small teams."),
                                    ("verifier", "verify"): verdict(["PASS"], ids=("1",)), ("sales_lead", "deliver"): delivery_any,
                                    ("fact_checker", "factcheck"): proof_true("Plans start at $49", "owner:request")})
    await d.handle_message(msg("write a price line: plans start at $49"))
    phases = [c["phase"] for c in runner.calls]
    assert "factcheck" in phases and "deliver" not in phases   # C10: numbers -> Proof; the delivery note is built in code
    assert phases.index("factcheck") < phases.index("verify")              # Proof first, then Vera on every task


def proof_true(claim, source):
    async def fn(tools, ctx):
        r = await tools["submit_factcheck"].handler({"claims": [{"quote": claim, "claim": claim, "verdict": "TRUE", "sources": [source],
                                                                  "evidence": "matches"}]})
        assert not r.get("is_error"), r
    return fn


async def delivery_any(tools, ctx):
    await tools["submit_delivery"].handler({"note": "Done."})


# ---------------------------------------------------------------- C14
def test_pending_actions_validated(cfg):
    echo = cfg.employee("sales_writer")
    assert validate_pending_actions(cfg, echo, [{"action": "email.send_external", "params": {}, "preview": "p"}]) == []
    assert validate_pending_actions(cfg, echo, [{"action": "apply.submit", "preview": "p"}])      # not allowlisted
    assert validate_pending_actions(cfg, echo, [{"action": "social.draft", "preview": "p"}])            # R1
    assert validate_pending_actions(cfg, echo, [{"action": "config.modify", "preview": "p"}])           # R4
    assert validate_pending_actions(cfg, echo, [{"action": "email.send_external", "params": {}}])            # no preview


# ---------------------------------------------------------------- C15 C16 C17
def test_owner_only_gates(cfg):
    p = Policy(cfg)
    p.p["approval_policy"]["approvers"]["backup"] = ["U_BACKUP"]
    try:
        assert not p.can_approve("U_BACKUP", "OWNER", "sales")   # C15
        assert p.can_approve("U_BACKUP", "R2", "sales")
    finally:
        p.p["approval_policy"]["approvers"]["backup"] = []


async def test_r3_double_confirm_and_single_click(make_dispatcher):
    d, _, _ = make_dispatcher({})
    with d.Session() as db:
        db.add(Task(id="t3", department="sales", requested_by=OWNER, original_request="x", contract_version=1,
                    status="CLOSED"))
        db.add(Approval(id="g3", task_id="t3", gate="G3", tier="R3", action="payments.any", action_hash="h",
                        contract_version=1, preview={"employee": "sales_writer", "params": {}}))
        db.commit()
    assert await d.on_approval(OWNER, "g3", True, button_hash="h") == "confirm-needed"   # C16
    assert await d.on_approval(OWNER, "g3", True, button_hash="h") == "ok"
    assert await d.on_approval(OWNER, "g3", True, button_hash="h") == "stale"            # C17


# ---------------------------------------------------------------- C18 C19
async def test_owner_steering_stops_running_loop(make_dispatcher):
    holder = {}

    async def steer_mid_run(tools, ctx):
        await writer(COPY)(tools, ctx)
        await holder["d"].steer(task(holder["d"]).id, OWNER, "actually make it about pricing")
    d, runner, _ = make_dispatcher({("sales_lead", "contract"): two_step_contract(), ("sales_lead", "plan"): two_step_plan,
                                    ("sales_ideas", "execute"): steer_mid_run})
    holder["d"] = d
    await d.handle_message(msg("please do the task"))
    await approve(d, "G1")
    execs = [c["employee"] for c in runner.calls if c["phase"] == "execute"]
    assert execs == ["sales_ideas"]                           # T2 never ran on the old contract
    t = task(d)
    assert t.status == "CONTRACT_DRAFTED" and t.contract_version == 2


async def test_revision_round_archived(make_dispatcher):
    d, _, _ = make_dispatcher({
        ("sales_lead", "contract"): two_step_contract(), ("sales_lead", "plan"): two_step_plan,
        ("sales_ideas", "execute"): writer(COPY), ("sales_writer", "execute"): poster({}),
        ("verifier", "verify"): verdict(["FAIL", "PASS"]), ("sales_lead", "deliver"): delivery})
    await d.handle_message(msg("please do the task and verify"))
    await approve(d, "G1")
    t = task(d)
    assert t.status == "DELIVERED"
    w = hmod.task_dir(t.id)
    assert (w / "rounds" / "r1" / "T1").is_dir() and (w / "rounds" / "r1" / "artifacts" / "T1-out.md").exists()  # C19


# ---------------------------------------------------------------- C20
async def test_cross_department_request_and_resume(make_dispatcher, render_stub):
    """Studio asks Sales for the Sherlock script (ideas -> write), then Frame builds from Sales' artifact."""
    calls = {"plan": 0}

    async def studio_contract(tools, ctx):
        r = await tools["submit_contract"].handler({
            "objective": "Sherlock reel on planners", "size": "M",
            "deliverables": [{"id": "D1", "description": "video", "assignee": "studio_builder", "task_type": "sherlock_reel"}],
            "acceptance_criteria": [{"id": "1", "text": "video", "check": "automatic"}]})
        assert not r.get("is_error"), r

    async def studio_plan(tools, ctx):
        calls["plan"] += 1
        if calls["plan"] == 1:
            r = await tools["submit_plan"].handler({"handoffs": [{"deliverable": "D1", "to": "studio_builder",
                                                                  "task_type": "sherlock_reel", "objective": "v", "criteria": ["1"]}]})
            assert r.get("is_error") and "output made by" in r["content"][0]["text"]   # never writes its own script
            r = await tools["submit_plan"].handler({"cross_dept": [{"department": "sales", "objective": "script on planners",
                                                                    "acceptance_criteria": [{"id": "1", "text": "script"}]}]})
            assert not r.get("is_error"), r
            return
        refs = re.findall(r"artifact://\S+?X-sales-[\w.-]+", ctx["prompt"])
        assert refs, "lead must be offered the sales artifacts"
        r = await tools["submit_plan"].handler({"handoffs": [{"deliverable": "D1", "to": "studio_builder",
                                                              "task_type": "sherlock_reel", "objective": "v", "criteria": ["1"],
                                                              "inputs": [refs[-1].rstrip('",')]}]})
        assert not r.get("is_error"), r

    async def sales_plan(tools, ctx):
        r = await tools["submit_plan"].handler({"handoffs": [
            {"to": "sales_ideas", "task_type": "generate_ideas", "objective": "research", "criteria": ["1"]},
            {"to": "show_sherlock_writer", "task_type": "sherlock_script", "objective": "script", "criteria": ["1"],
             "inputs_from": ["T1"]}]})
        assert not r.get("is_error"), r

    async def video_from_sales(tools, ctx):
        got = await tools["workspace_read"].handler({"ref": re.findall(r"artifact://\S+?X-sales-[\w.-]+", ctx["prompt"])[0].rstrip('",')})
        assert not got.get("is_error"), got
        await writer("render placeholder")(tools, ctx)

    d, runner, _ = make_dispatcher({
        ("studio_lead", "contract"): studio_contract, ("studio_lead", "plan"): studio_plan,
        ("sales_lead", "plan"): sales_plan, ("sales_ideas", "execute"): writer("Planners help small teams."),
        ("show_sherlock_writer", "execute"): writer(COPY),
        ("sales_lead", "deliver"): delivery_any, ("studio_builder", "execute"): video_from_sales,
        ("verifier", "verify"): verdict(["PASS"], ids=("1",)), ("studio_lead", "deliver"): delivery_any})
    await d.handle_message(msg("sherlock reel on planners", channel="#studio"))
    await approve(d, "G1")
    with d.Session() as db:
        parent = db.scalars(select(Task).where(Task.parent_id.is_(None))).first()
        child = db.scalar(select(Task).where(Task.parent_id == parent.id))
        assert parent.status == "WAITING_ON_DEPT" and child.department == "sales" and child.status == "DELIVERED"
        assert db.scalar(select(AuditEvent).where(AuditEvent.kind == "cos.relay")) is not None
        g4 = db.scalar(select(Approval).where(Approval.task_id == child.id, Approval.gate == "G4"))
    await d.on_approval(OWNER, g4.id, True)
    assert task(d).status == "DELIVERED"                                   # parent resumed and finished


# ---------------------------------------------------------------- C21 C22
async def test_sweep_reminds_parks_and_recovers(make_dispatcher):
    d, _, slack = make_dispatcher({})
    now = datetime.now(timezone.utc)
    with d.Session() as db:
        db.add(Task(id="a", department="sales", requested_by=OWNER, original_request="x", contract_version=1, status="CONTRACT_DRAFTED"))
        db.add(Task(id="b", department="sales", requested_by=OWNER, original_request="x", contract_version=1, status="IN_PROGRESS",
                    plan=[{"to": "sales_writer"}]))
        db.add(Approval(id="r1", task_id="a", gate="G1", contract_version=1, created_at=now - timedelta(hours=5)))
        db.add(Approval(id="r2", task_id="a", gate="G1", contract_version=1, created_at=now - timedelta(hours=80)))
        db.add(Pause(scope="all", reason="budget:2000-01: used", by="budget"))
        db.commit()
    rep = d.sweep(boot=True)
    assert rep["reminded"] == 1 and rep["expired"] == 1 and rep["resume"] == ["b"] and rep["resumed_budget"]
    rep = d.sweep(boot=True)                                                  # second restart: escalate, don't loop
    assert rep["interrupted"] == 1
    with d.Session() as db:
        assert db.get(Task, "b").status == "ESCALATED"
        assert db.get(Approval, "r2").status == "expired"
        assert db.get(Pause, "all") is None                                # C22


# ---------------------------------------------------------------- C23 C24 C25
async def test_standing_rule_capture(make_dispatcher):
    d, runner, slack = make_dispatcher({("sales_lead", "contract"): two_step_contract()})
    await d.handle_message(msg("From now on keep captions under 100 characters. Write one for the launch."))
    assert await approve(d, "GM") == "ok"
    with d.Session() as db:
        m = db.scalar(select(MemoryEntry).where(MemoryEntry.layer == "L1"))
        assert m.status == "active" and m.standing and m.scope_id == "sales"


async def test_rejection_feedback_filtered(make_dispatcher):
    d, _, _ = make_dispatcher({
        ("sales_lead", "contract"): two_step_contract(), ("sales_lead", "plan"): two_step_plan,
        ("sales_ideas", "execute"): writer(COPY), ("sales_writer", "execute"): poster({}),
        ("verifier", "verify"): verdict(["PASS"]), ("sales_lead", "deliver"): delivery})
    await d.handle_message(msg("please do the task"))
    await approve(d, "G1")
    with d.Session() as db:
        g4 = db.scalar(select(Approval).where(Approval.gate == "G4"))
    await d.on_approval(OWNER, g4.id, False, reason="send it to jane@corp.com instead")
    with d.Session() as db:
        fb = list(db.scalars(select(MemoryEntry).where(MemoryEntry.content.like("Owner rejected%"))))
    assert fb and all(m.status == "rejected" for m in fb)                   # C24 PII never saved


def test_workspace_writes_counted(cfg, Session):
    p, quill = Policy(cfg), cfg.employee("sales_writer")
    with Session() as db:
        t = Task(id="w", department="sales", requested_by=OWNER, original_request="x", contract_version=1)
        db.add(t)
        db.flush()
        outs = [p.check(db, quill, "workspace.write", {"tool": "workspace_write"}, t).outcome for _ in range(26)]
    assert outs[:25] == ["allow"] * 25 and outs[25] == "approval"          # C25


# ---------------------------------------------------------------- round 2: C26–C33
async def test_verifier_cannot_judge_owner_taste(make_dispatcher):
    seen = {}

    async def taste_contract(tools, ctx):
        await tools["submit_contract"].handler({
            "objective": "post_copy", "size": "M",
            "deliverables": [{"id": "D1", "description": "c", "assignee": "sales_writer", "task_type": "post_copy"}],
            "acceptance_criteria": [{"id": "1", "text": "accurate", "check": "verifier"},
                                    {"id": "2", "text": "feels on-brand", "check": "owner_taste"}]})

    async def taste_plan(tools, ctx):
        await tools["submit_plan"].handler({"handoffs": [
            {"deliverable": "D1", "to": "sales_writer", "task_type": "post_copy", "objective": "c", "criteria": ["1"]}]})

    async def judge(tools, ctx):
        r = await tools["submit_verdict"].handler({"grades": [{"criterion_id": "1", "result": "PASS", "evidence": "e"},
                                                              {"criterion_id": "2", "result": "FAIL", "evidence": "meh"}]})
        seen["err"] = r["content"][0]["text"]
        await tools["submit_verdict"].handler({"grades": [{"criterion_id": "1", "result": "PASS", "evidence": "e"},
                                                          {"criterion_id": "2", "result": "UNVERIFIABLE", "evidence": "taste"}]})
    d, _, slack = make_dispatcher({("sales_lead", "contract"): taste_contract, ("sales_lead", "plan"): taste_plan,
                                   ("sales_writer", "execute"): writer(COPY), ("verifier", "verify"): judge,
                                   ("sales_lead", "deliver"): delivery_any})
    await d.handle_message(msg("please do the task, verify it"))
    await approve(d, "G1")
    assert "owner's taste" in seen["err"] and task(d).status == "DELIVERED"
    assert "Your call (taste)" in json.dumps(slack.sent)


async def test_act_rejects_internal_actions(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({})
    with d.Session() as db:
        db.add(Task(id="ta", department="sales", requested_by=OWNER, original_request="x", contract_version=1))
        db.commit()
    r = await d._act_tool(cfg.employee("sales_writer"), "ta").handler({"action": "workspace.write"})
    assert "dedicated tool" in r["content"][0]["text"]                     # C27


def test_pending_action_tier_must_be_in_contract(cfg):
    echo = cfg.employee("sales_writer")
    pa = [{"action": "email.send_external", "params": {}, "preview": "p"}]
    assert validate_pending_actions(cfg, echo, pa, approved_tiers=set())       # C28 S task declared none
    assert validate_pending_actions(cfg, echo, pa, approved_tiers={"R2"}) == []


async def test_vera_checks_every_task_against_the_original_request(make_dispatcher):
    """DECIDED (2026-10): Vera grades EVERY delivery against your original words; 'verify' after delivery re-checks."""
    async def c(tools, ctx):
        await tools["submit_contract"].handler({
            "objective": "post_copy", "size": "M",
            "deliverables": [{"id": "D1", "description": "c", "assignee": "sales_writer", "task_type": "post_copy"}],
            "acceptance_criteria": [{"id": "1", "text": "matches the launch doc", "check": "verifier"}]})

    async def p(tools, ctx):
        await tools["submit_plan"].handler({"handoffs": [
            {"deliverable": "D1", "to": "sales_writer", "task_type": "post_copy", "objective": "c", "criteria": ["1"]}]})
    d, runner, slack = make_dispatcher({("sales_lead", "contract"): c, ("sales_lead", "plan"): p,
                                        ("sales_writer", "execute"): writer(COPY),
                                        ("verifier", "verify"): verdict(["PASS"], ids=("1",)), ("sales_lead", "deliver"): delivery_any})
    await d.handle_message(msg("please do the task"))
    await approve(d, "G1")
    vera = [x for x in runner.calls if x["phase"] == "verify"]
    assert task(d).status == "DELIVERED" and len(vera) == 1                   # not asked — Vera ran anyway
    assert '<owner_request id="original">' in vera[0]["prompt"] and "please do the task" in vera[0]["prompt"]
    await d.handle_message(msg("verify", eid="E9", thread="100.1"))
    assert [x["phase"] for x in runner.calls].count("verify") == 2 and task(d).status == "DELIVERED"
    with d.Session() as db:
        g4 = sorted(a.status for a in db.scalars(select(Approval).where(Approval.gate == "G4")))
    assert g4 == ["expired", "pending"]                                   # fresh card with Vera's grades


async def test_steering_cancels_orphaned_children(make_dispatcher):
    d, _, _ = make_dispatcher({("sales_lead", "contract"): two_step_contract()})
    with d.Session() as db:
        db.add(Task(id="p", department="sales", requested_by=OWNER, original_request="x", contract_version=1,
                    status="WAITING_ON_DEPT", slack_thread="T1"))
        db.add(Task(id="k", parent_id="p", department="sales", requested_by=OWNER, original_request="y",
                    contract_version=1, status="IN_PROGRESS"))
        db.commit()
    await d.steer("p", OWNER, "change of plan")
    with d.Session() as db:
        assert db.get(Task, "k").status == "CANCELLED"                       # C30


def test_lead_text_never_counts_as_owner_trigger(cfg, make_dispatcher):
    d, _, _ = make_dispatcher({})
    with d.Session() as db:
        db.add(Task(id="root", department="sales", requested_by=OWNER, original_request="make an ai reel", contract_version=1))
        db.add(Task(id="kid", parent_id="root", department="sales", requested_by=OWNER,
                    original_request="sherlock reel please", contract_version=1))
        db.commit()
        kid = db.get(Task, "kid")
    assert "sherlock" not in d._owner_text(kid)                              # C31


def test_company_wide_rules_visible_to_all(cfg, Session):
    from workforce.memory import MemoryStore
    ms = MemoryStore(cfg)
    with Session() as db:
        db.add(MemoryEntry(id="hq1", layer="L1", scope_id="hq", kind="preference", content="never use emojis",
                           source="owner", author="owner", status="active"))
        db.commit()
        assert [m.id for m in ms.read(db, cfg.employee("office_architect"), "emojis")] == ["hq1"]   # C32


async def test_artifact_size_cap(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({})
    tools = {t.name: t for t in d._common_tools(cfg.employee("sales_writer"), "tz", "T1", set(), {})}
    r = await tools["workspace_write"].handler({"name": "big.md", "content": "x" * 2_000_001})
    assert r.get("is_error")                                                 # C33


async def test_reject_without_reason_waits_for_owner(make_dispatcher):
    d, runner, slack = make_dispatcher({
        ("sales_lead", "contract"): two_step_contract(), ("sales_lead", "plan"): two_step_plan,
        ("sales_ideas", "execute"): writer(COPY), ("sales_writer", "execute"): poster({}),
        ("verifier", "verify"): verdict(["PASS"]), ("sales_lead", "deliver"): delivery})
    await d.handle_message(msg("please do the task"))
    await approve(d, "G1")
    plans_before = [c["phase"] for c in runner.calls].count("plan")
    with d.Session() as db:
        g4 = db.scalar(select(Approval).where(Approval.gate == "G4"))
    await d.on_approval(OWNER, g4.id, False)
    assert task(d).status == "REJECTED"
    assert [c["phase"] for c in runner.calls].count("plan") == plans_before       # C35 no blind re-plan
    await d.handle_message(msg("make the post shorter", eid="E7", thread="100.1"))
    assert "make the post shorter" in [c for c in runner.calls if c["phase"] == "plan"][-1]["prompt"]


# ---------------------------------------------------------------- live-run findings (L1–L3)
def test_numeric_ids_normalized():
    from workforce.dispatcher import normalize_ids
    got = normalize_ids({"acceptance_criteria": [{"id": 1, "text": "t"}], "handoffs": [{"criteria": [1, 2], "inputs_from": ["T1"]}],
                         "self_check": [{"criterion_id": 3, "result": "met"}]})
    assert got["acceptance_criteria"][0]["id"] == "1" and got["handoffs"][0]["criteria"] == ["1", "2"]
    assert got["self_check"][0]["criterion_id"] == "3"


async def test_malformed_return_rejected_in_session(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({})
    with d.Session() as db:
        db.add(Task(id="tm", department="sales", requested_by=OWNER, original_request="x", contract_version=1,
                    contract={"planned_actions_tiers": []}))
        db.commit()
    sink, ctx = {}, {}
    tools = {t.name: t for t in d._common_tools(cfg.employee("sales_writer"), "tm", "T1", set(), ctx)}
    ref = ref_of(await tools["workspace_write"].handler({"name": "c.md", "content": COPY}))
    submit = d._submit_return_tool(cfg.employee("sales_writer"), "tm", "T1", sink, ctx)
    r = await submit.handler({"status": "done", "outputs": [ref], "confidence": 0.9,
                              "self_check": [{"criterion": "1", "status": "met"}]})
    assert r.get("is_error") and "malformed" in r["content"][0]["text"] and "return" not in sink
    r = await submit.handler({"status": "done", "outputs": [ref], "confidence": 0.9,
                              "self_check": [{"criterion_id": 1, "result": "met", "evidence": "ok"}]})
    assert not r.get("is_error") and sink["return"]["self_check"][0]["criterion_id"] == "1"
