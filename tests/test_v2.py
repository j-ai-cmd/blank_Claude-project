"""Org v2: show isolation (I1–I7), Proof (fact checker), Talent hire flow, research → write chains."""
import re
import subprocess
import sys

import yaml
from sqlalchemy import select

from workforce.slack import InboundMessage
from tests.test_flags import OWNER, approve, delivery_any, msg, ref_of, task, verdict, writer
from workforce.config import ROOT
from workforce.db import Approval, MemoryEntry, Task
from workforce.dispatcher import validate_contract, validate_plan
from workforce.memory import MemoryStore
from workforce.policy import ALLOW, DENY, Policy
from workforce.prompts import system_prompt
from workforce.routing import resolve

BASE = {"objective": "x", "size": "M", "acceptance_criteria": [{"id": "1", "text": "t", "check": "automatic"}]}


# ------------------------------------------------------------------ I1 one show per task, explicit only
def test_I1_show_employees_only_on_their_own_show(cfg, runtimes):
    studio = cfg.employee("studio_lead")
    jai_reel = [{"id": "D1", "assignee": "show_jai_producer", "task_type": "jai_reel"}]
    sher_reel = [{"id": "D1", "assignee": "show_sherlock_producer", "task_type": "sherlock_reel"}]
    reel = [{"id": "D1", "assignee": "studio_faceless_editor", "task_type": "explainer_video"}]
    assert not validate_contract({**BASE, "deliverables": jai_reel}, studio, cfg, "jai reel", show="jai")
    # Sherlock can never be given Jai's video, even though both make videos
    assert any("only on the 'sherlock' show" in p for p in validate_contract({**BASE, "deliverables": sher_reel}, studio, cfg, show="jai"))
    # no show named -> show employees unavailable
    assert any("names no show" in p for p in validate_contract({**BASE, "deliverables": jai_reel}, studio, cfg, show=None))
    # non-show helpers (Reel/Pixel/Script) are barred from a show task
    assert any("doesn't work on show tasks" in p for p in validate_contract({**BASE, "deliverables": reel}, studio, cfg, show="jai"))
    sales = cfg.employee("sales_lead")
    script = [{"id": "D1", "assignee": "sales_script_writer", "task_type": "video_script"}]
    assert any("doesn't work on show tasks" in p for p in validate_contract({**BASE, "deliverables": script}, sales, cfg, show="peter"))
    # the one shared helper: Intel researches for a show
    intel = [{"id": "D1", "assignee": "sales_researcher", "task_type": "topic_research"}]
    assert not validate_contract({**BASE, "deliverables": intel}, sales, cfg, show="striker")


def test_I1_show_detection(cfg):
    assert cfg.shows_named("make a jai reel about coffee") == ["jai"]
    assert cfg.shows_named("football video on ISL") == ["striker"]
    assert cfg.shows_named("jaipur trip vlog") == []                       # whole words only
    assert sorted(cfg.shows_named("a jai reel and a sherlock reel")) == ["jai", "sherlock"]
    assert cfg.shows_named("pitch email to Peter at Acme") == []           # a name is not a show
    assert cfg.shows_named("show: peter") == ["peter"]


async def test_I1_two_shows_in_one_message_asks_owner(make_dispatcher, runtimes):
    async def jai_contract(tools, ctx):
        assert "belongs to the show 'jai'" in ctx["system"]
        r = await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "reel", "assignee": "show_jai_producer", "task_type": "jai_reel"}]})
        assert not r.get("is_error"), r
    d, runner, slack = make_dispatcher({("studio_lead", "contract"): jai_contract})
    await d.handle_message(msg("make a jai reel and a sherlock reel", channel="#studio"))
    assert runner.calls == [] and task(d).status == "RECEIVED"             # nothing runs, no credit spent
    assert any("one show" in m.get("text", "") for m in slack.sent)
    await d.handle_message(msg("both", eid="E2", thread="100.1", channel="#studio"))
    assert runner.calls == []                                               # still waiting for exactly one
    await d.handle_message(msg("jai", eid="E3", thread="100.1", channel="#studio"))
    t = task(d)
    assert t.show == "jai" and t.status == "CONTRACT_DRAFTED"


async def test_I1_reply_naming_another_show_is_not_a_silent_switch(make_dispatcher):
    async def c(tools, ctx):
        await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "reel", "assignee": "show_sherlock_producer", "task_type": "sherlock_reel"}]})
    d, runner, slack = make_dispatcher({("studio_lead", "contract"): c})
    await d.handle_message(msg("sherlock reel on transformers", channel="#studio"))
    await d.handle_message(msg("make it feel like the jai reels", eid="E2", thread="100.1", channel="#studio"))
    assert task(d).show == "sherlock" and len(runner.calls) == 1
    assert any("switch to" in m.get("text", "") for m in slack.sent)


def test_I1_lead_roster_shows_only_allowed_employees(cfg):
    maya = cfg.employee("studio_lead")
    jai = system_prompt(cfg, maya, "contract", show="jai")
    none = system_prompt(cfg, maya, "contract", show=None)
    roster = lambda sp: sp.split("# Your specialists available")[1].split("\n# ")[0]   # noqa: E731
    assert '"show_jai_producer"' in roster(jai) and '"show_sherlock_producer"' not in roster(jai)
    assert '"studio_faceless_editor"' not in roster(jai)
    assert '"studio_faceless_editor"' in roster(none) and '"show_jai_producer"' not in roster(none)


# ------------------------------------------------------------------ I2 one owner per task type
def test_I2_task_types_unique_org_wide(cfg):
    owners = {}
    for eid in cfg.employees:
        for tt in cfg.routes(eid):
            assert tt not in owners, f"{tt}: {owners.get(tt)} and {eid}"
            owners[tt] = eid
    out = subprocess.run([sys.executable, str(ROOT / "scripts/validate_config.py")], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout


# ------------------------------------------------------------------ I3/I4 memory per show
def test_I3_I4_memory_never_crosses_shows(cfg, Session):
    ms = MemoryStore(cfg)
    with Session() as db:
        t_jai = Task(id="tj", department="sales", requested_by=OWNER, original_request="x", show="jai")
        t_none = Task(id="tn", department="sales", requested_by=OWNER, original_request="x")
        db.add_all([t_jai, t_none])
        db.flush()
        intel, sher_writer = cfg.employee("sales_researcher"), cfg.employee("show_sherlock_writer")
        m1 = ms.submit_candidate(db, intel, t_jai, "Jai audience likes coffee topics", layer="L3")
        m2 = ms.submit_candidate(db, cfg.employee("show_jai_writer"), t_jai, "Jai signs off with 'peace'", layer="L1")
        m3 = ms.submit_candidate(db, intel, t_none, "Client Acme prefers short briefs", layer="L3")
        for m in (m1, m2, m3):
            m.status = "active"
        db.flush()
        assert m1.scope_id == "sales_researcher@jai" and m2.scope_id == "show:jai" and m3.scope_id == "sales_researcher"
        read = lambda e, show=None: {m.id for m in ms.read(db, e, "", show=show)}   # noqa: E731
        assert m1.id in read(intel, "jai") and m1.id not in read(intel, "sherlock") and m1.id not in read(intel)
        assert m2.id in read(cfg.employee("show_jai_producer")) and m2.id not in read(sher_writer)
        assert m2.id not in read(cfg.employee("sales_script_writer"))           # not the whole Sales dept
        assert m3.id in read(intel, "jai")                                      # its own general memory is fine


async def test_I3_standing_rule_on_show_task_is_scoped_to_show(make_dispatcher):
    d, _, _ = make_dispatcher({})
    await d.handle_message(msg("sherlock reels: always open with a deduction", channel="#studio"))
    with d.Session() as db:
        m = db.scalar(select(MemoryEntry).where(MemoryEntry.standing.is_(True)))
    assert m.scope_id == "show:sherlock"


# ------------------------------------------------------------------ I5 voice + show bible belong to one show
def test_I5_owner_voice_only_for_jai(cfg, Session):
    p = Policy(cfg)
    with Session() as db:
        t = Task(id="tv", department="studio", requested_by=OWNER, original_request="x")
        db.add(t)
        db.flush()
        assert p.check(db, cfg.employee("show_jai_producer"), "voice.synthesize", {"voice": "owner_clone"}, t).outcome == ALLOW
        assert p.check(db, cfg.employee("show_sherlock_producer"), "voice.synthesize", {"voice": "owner_clone"}, t).outcome == DENY
        assert p.check(db, cfg.employee("studio_faceless_editor"), "voice.synthesize", {"voice": "owner_clone"}, t).outcome == DENY
        assert p.check(db, cfg.employee("show_sherlock_producer"), "voice.synthesize", {"voice": "base"}, t).outcome == ALLOW
        assert p.check(db, cfg.employee("show_peter_producer"), "voice.synthesize", {"voice": "base"}, t).outcome == DENY


def test_I5_show_bible_and_training_only_in_own_prompt(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "show_bible", lambda s: f"BIBLE-OF-{s}")
    jai = system_prompt(cfg, cfg.employee("show_jai_writer"), "execute", resolve(cfg, "show_jai_writer", "jai_script"))
    sher = system_prompt(cfg, cfg.employee("show_sherlock_writer"), "execute")
    assert "BIBLE-OF-jai" in jai and "BIBLE-OF-jai" not in sher and "BIBLE-OF-sherlock" in sher
    assert "`show_jai_writer`" in jai and "`show_jai_writer`" not in sher


def test_I5_placeholder_bible_means_stop_and_ask(cfg):
    sp = system_prompt(cfg, cfg.employee("show_peter_writer"), "execute")
    assert "No show bible exists yet" in sp and "TODO (owner)" not in sp


# ------------------------------------------------------------------ I6 per-show capacity
async def test_I6_one_show_cannot_take_every_slot(make_dispatcher):
    d, _, slack = make_dispatcher({})
    with d.Session() as db:
        for i in range(2):
            db.add(Task(id=f"j{i}", department="studio", requested_by=OWNER, original_request="jai", show="jai",
                        status="IN_PROGRESS"))
        db.commit()
    assert d._dept_busy("studio", show="jai") and not d._dept_busy("studio", show="sherlock")


# ------------------------------------------------------------------ I7 auditors keep no memory
def test_I7_auditors_have_no_memory(cfg, Session):
    ms = MemoryStore(cfg)
    assert ms.readable_scopes(cfg.employee("verifier")) == [] and ms.readable_scopes(cfg.employee("fact_checker")) == []
    for eid in ("verifier", "fact_checker"):
        assert "memory.submit_candidate" not in cfg.employee(eid).tools


# ------------------------------------------------------------------ research -> write (needs_upstream)
def test_writers_and_producers_need_upstream(cfg):
    sam = cfg.employee("sales_lead")
    contract = {**BASE, "deliverables": [{"id": "D1", "assignee": "sales_outreach_writer", "task_type": "pitch_email"}]}
    _, prob = validate_plan(cfg, sam, "t", contract, 1, "M", [
        {"deliverable": "D1", "to": "sales_outreach_writer", "task_type": "pitch_email", "objective": "o", "criteria": ["1"]}], "", False)
    assert any("output made by" in p for p in prob)
    contract["deliverables"].insert(0, {"id": "D0", "assignee": "sales_researcher", "task_type": "account_brief"})
    _, prob = validate_plan(cfg, sam, "t", contract, 1, "M", [
        {"deliverable": "D0", "to": "sales_researcher", "task_type": "account_brief", "objective": "o", "criteria": ["1"]},
        {"deliverable": "D1", "to": "sales_outreach_writer", "task_type": "pitch_email", "objective": "o", "criteria": ["1"],
         "inputs_from": ["T1"]}], "", False)
    assert prob == []


async def test_show_reel_script_comes_from_the_shows_own_writer(make_dispatcher, render_stub):
    """'jai reel' in #studio -> Sales child task (inherits show jai) -> Intel -> Jai-Writer -> Jai builds it."""
    calls = {"plan": 0}

    async def maya_contract(tools, ctx):
        r = await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "reel", "assignee": "show_jai_producer", "task_type": "jai_reel"}]})
        assert not r.get("is_error"), r

    async def maya_plan(tools, ctx):
        calls["plan"] += 1
        if calls["plan"] == 1:
            r = await tools["submit_plan"].handler({"cross_dept": [{"department": "sales", "objective": "jai script on coffee",
                                                                    "acceptance_criteria": [{"id": "1", "text": "script"}]}]})
            assert not r.get("is_error"), r
            return
        ref = re.findall(r"artifact://\S+?X-sales-T2[\w.-]+", ctx["prompt"])[0].rstrip('",')
        brief = re.findall(r"artifact://\S+?X-sales-T1[\w.-]+", ctx["prompt"])[0].rstrip('",')
        bad = await tools["submit_plan"].handler({"handoffs": [{"deliverable": "D1", "to": "show_jai_producer",
                                                                "task_type": "jai_reel", "objective": "reel", "criteria": ["1"], "inputs": [brief]}]})
        assert bad.get("is_error") and "show_jai_writer" in bad["content"][0]["text"]   # research alone isn't a script
        r = await tools["submit_plan"].handler({"handoffs": [{"deliverable": "D1", "to": "show_jai_producer",
                                                              "task_type": "jai_reel", "objective": "reel", "criteria": ["1"], "inputs": [ref]}]})
        assert not r.get("is_error"), r

    async def sam_plan(tools, ctx):
        assert '"show_jai_writer"' in ctx["system"] and '"sales_script_writer"' not in ctx["system"]
        bad = await tools["submit_plan"].handler({"handoffs": [
            {"to": "sales_researcher", "task_type": "topic_research", "objective": "r", "criteria": ["1"]},
            {"to": "show_sherlock_writer", "task_type": "sherlock_script", "objective": "s", "criteria": ["1"], "inputs_from": ["T1"]}]})
        assert bad.get("is_error") and "only on the 'sherlock' show" in bad["content"][0]["text"]
        r = await tools["submit_plan"].handler({"handoffs": [
            {"to": "sales_researcher", "task_type": "topic_research", "objective": "r", "criteria": ["1"]},
            {"to": "show_jai_writer", "task_type": "jai_script", "objective": "s", "criteria": ["1"], "inputs_from": ["T1"]}]})
        assert not r.get("is_error"), r

    d, runner, _ = make_dispatcher({
        ("studio_lead", "contract"): maya_contract, ("studio_lead", "plan"): maya_plan, ("studio_lead", "deliver"): delivery_any,
        ("sales_lead", "plan"): sam_plan, ("sales_lead", "deliver"): delivery_any,
        ("sales_researcher", "execute"): writer("Coffee helps people focus in the morning."),
        ("show_jai_writer", "execute"): writer("So I tried coffee at dawn. Here is what happened."),
        ("show_jai_producer", "execute"): writer("render placeholder"), ("verifier", "verify"): verdict(["PASS"], ids=("1",))})
    await d.handle_message(msg("jai reel about morning coffee", channel="#studio"))
    await approve(d, "G1")
    with d.Session() as db:
        child = db.scalar(select(Task).where(Task.parent_id.is_not(None)))
        assert child.show == "jai" and child.status == "DELIVERED"                 # sub-task inherits the show
        g4 = db.scalar(select(Approval).where(Approval.task_id == child.id, Approval.gate == "G4"))
    await d.on_approval(OWNER, g4.id, True)
    assert task(d).status == "DELIVERED"
    execs = [c["employee"] for c in runner.calls if c["phase"] == "execute"]
    assert execs == ["sales_researcher", "show_jai_writer", "show_jai_producer"]


# ------------------------------------------------------------------ Proof (fact checker)
def _one_step(to, tt, text, size="S", extra_scripts=None):
    async def c(tools, ctx):
        r = await tools["submit_contract"].handler({"objective": "o", "size": size, "deliverables": [
            {"id": "D1", "description": "d", "assignee": to, "task_type": tt}],
            "acceptance_criteria": [{"id": "1", "text": "t", "check": "automatic"}]})
        assert not r.get("is_error"), r

    async def p(tools, ctx):
        r = await tools["submit_plan"].handler({"handoffs": [{"deliverable": "D1", "to": to, "task_type": tt,
                                                              "objective": "o", "criteria": ["1"]}]})
        assert not r.get("is_error"), r
    return {("sales_lead", "contract"): c, ("sales_lead", "plan"): p, (to, "execute"): writer(text),
            ("sales_lead", "deliver"): delivery_any, **(extra_scripts or {})}


async def test_proof_false_claim_goes_back_to_writer(make_dispatcher):
    runs = {"n": 0}

    async def proof(tools, ctx):
        runs["n"] += 1
        bad = await tools["submit_factcheck"].handler({"claims": [
            {"quote": "Plans start at", "claim": "made up", "verdict": "TRUE", "sources": ["https://never-fetched.example"], "evidence": "trust me"}]})
        assert bad.get("is_error")                                   # can't mark TRUE on a source it never opened
        if runs["n"] == 1:
            lazy = await tools["submit_factcheck"].handler({"claims": [
                {"quote": "Plans start at $49", "claim": "Plans start at $49", "verdict": "TRUE", "sources": ["owner:request"], "evidence": "looks right"}]})
            assert lazy.get("is_error") and "49" in lazy["content"][0]["text"]   # the number isn't in your request
            claim = {"quote": "Plans start at $49", "claim": "Plans start at $49", "verdict": "FALSE", "sources": ["owner:request"], "evidence": "request says $39"}
        else:
            claim = {"quote": "Plans start at $39", "claim": "Plans start at $39", "verdict": "TRUE", "sources": ["owner:request"], "evidence": "matches"}
        r = await tools["submit_factcheck"].handler({"claims": [claim]})
        assert not r.get("is_error"), r
    texts = iter(["Plans start at $49 a month.", "Plans start at $39 a month."])

    async def script(tools, ctx):
        await writer(next(texts))(tools, ctx)
    d, runner, slack = make_dispatcher(_one_step("sales_script_writer", "caption", "", extra_scripts={
        ("fact_checker", "factcheck"): proof, ("sales_script_writer", "execute"): script}))
    await d.handle_message(msg("caption: plans start at $39 a month"))
    t = task(d)
    assert t.status == "DELIVERED" and t.revisions == 1
    execs = [c for c in runner.calls if c["phase"] == "execute"]
    assert "fact_check_failed" in execs[1]["prompt"] and "Plans start at $49" in execs[1]["prompt"]   # writer sees the claim
    assert any("Proof (facts)" in str(m) for m in slack.sent)


async def test_proof_offline_when_task_holds_private_data(make_dispatcher):
    async def proof(tools, ctx):
        assert "do NOT use the web" in ctx["prompt"]
        await tools["submit_factcheck"].handler({"claims": []})
    d, runner, _ = make_dispatcher({("fact_checker", "factcheck"): proof})
    with d.Session() as db:
        db.add(Task(id="tp", department="sales", requested_by=OWNER, original_request="x", contract_version=1,
                    status="VERIFYING", size="S", contract={"objective": "o", "acceptance_criteria": []},
                    plan=[{"to": "sales_application_writer", "task_type": "job_application"}]))
        db.commit()
    from workforce.harness import task_dir
    (task_dir("tp") / "artifacts").mkdir(parents=True)
    (task_dir("tp") / "artifacts" / "T1-cv.md").write_text("CV")
    await d.factcheck("tp")
    call = [c for c in runner.calls if c["phase"] == "factcheck"][-1]
    assert call["builtins"] == {}                                         # no WebSearch / WebFetch at all


def test_pii_allowed_only_where_contact_details_belong(cfg):
    assert "pii_absent" not in resolve(cfg, "sales_application_writer", "job_application").checks
    assert "pii_absent" not in resolve(cfg, "ops_bookkeeper", "invoice").checks
    assert "pii_absent" in resolve(cfg, "sales_outreach_writer", "pitch_email").checks


# ------------------------------------------------------------------ Talent
async def test_talent_never_autostarts_and_proposal_is_filed_not_applied(make_dispatcher, tmp_path, monkeypatch, cfg):
    spec = {"id": "studio_podcast_editor", "name": "Echo", "department": "studio", "kind": "specialist",
            "does": ["edit podcasts"], "does_not": ["publish"], "fire_when": "you ask for a podcast edit",
            "tools": ["workspace.read", "workspace.write", "submit_return"], "max_tier": "R1",
            "personality": {"voice": ["calm"]}, "routes": [{"task_type": "podcast_edit", "run": [], "checks": ["spellcheck"]}],
            "context": "Role: edits podcasts", "probation_tasks": ["a", "b", "c"], "pitch": "Meet Echo."}

    async def rhea_contract(tools, ctx):
        r = await tools["submit_contract"].handler({"objective": "design a podcast editor", "size": "S", "deliverables": [
            {"id": "D1", "description": "spec", "assignee": "talent_architect", "task_type": "design_employee"}],
            "acceptance_criteria": [{"id": "1", "text": "valid spec", "check": "automatic"}]})
        assert not r.get("is_error"), r

    async def rhea_plan(tools, ctx):
        await tools["submit_plan"].handler({"handoffs": [{"deliverable": "D1", "to": "talent_architect",
                                                          "task_type": "design_employee", "objective": "o", "criteria": ["1"]}]})

    async def architect(tools, ctx):
        ref = ref_of(await tools["workspace_write"].handler({"name": "spec.yaml", "content": yaml.safe_dump(spec)}))
        r = await tools["submit_return"].handler({"status": "done", "outputs": [ref], "confidence": 0.9,
                                                  "self_check": [{"criterion_id": "1", "result": "met", "evidence": "valid"}]})
        assert not r.get("is_error"), r
    monkeypatch.setattr(cfg, "dir", tmp_path / "config")
    d, runner, _ = make_dispatcher({("talent_lead", "contract"): rhea_contract, ("talent_lead", "plan"): rhea_plan,
                                    ("talent_architect", "execute"): architect, ("talent_lead", "deliver"): delivery_any})
    await d.handle_message(msg("I need someone to edit my podcast", channel="#talent"))
    assert task(d).status == "CONTRACT_DRAFTED"                         # S task, but Talent waits for your G1 (P4)
    await approve(d, "G1")
    assert task(d).status == "DELIVERED"
    await approve(d, "G4")
    assert (tmp_path / "proposals").is_dir() and list((tmp_path / "proposals").glob("*.yaml"))
    assert "studio_podcast_editor" not in (ROOT / "config/org.yaml").read_text()      # live config untouched


def test_employee_spec_check_rejects_unsafe_specs(tmp_path):
    from workforce.checks import main as check_main
    good = {"id": "x_new", "name": "N", "department": "ops", "kind": "specialist", "does": ["a"], "does_not": ["b"],
            "fire_when": "w", "tools": ["workspace.read"], "max_tier": "R1", "personality": {"voice": ["v"]},
            "routes": [{"task_type": "x_new_work", "run": [], "checks": ["spellcheck"]}], "context": "c",
            "probation_tasks": ["1", "2", "3"], "pitch": "p"}
    f = tmp_path / "s.yaml"
    f.write_text(yaml.safe_dump(good))
    assert check_main(["employee_spec", str(f)]) == 0
    for bad in ({"tools": ["payments.any"]}, {"max_tier": "R3"}, {"id": "sales_lead"},
                {"routes": [{"task_type": "caption", "run": [], "checks": ["spellcheck"]}]}, {"probation_tasks": ["1"]},
                {"tools": ["web.fetch", "finance.read_uploads"]}):
        f.write_text(yaml.safe_dump({**good, **bad}))
        assert check_main(["employee_spec", str(f)]) == 1, bad


async def test_owner_can_undo_a_wrong_show_detection(make_dispatcher):
    async def c(tools, ctx):
        await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "x", "assignee": "sales_researcher", "task_type": "job_brief"}]})
    d, _, _ = make_dispatcher({("sales_lead", "contract"): c})
    await d.handle_message(msg("research the video editor role at Jai reels studio"))
    assert task(d).show == "jai"
    await d.handle_message(msg("no show — it's a company name", eid="E2", thread="100.1"))
    assert task(d).show is None and task(d).contract_version == 2


async def test_proof_cannot_skip_claims_the_deliverable_states(make_dispatcher):
    seen = {}

    async def lazy_then_honest(tools, ctx):
        seen["lazy"] = await tools["submit_factcheck"].handler({"claims": []})
        seen["meta"] = await tools["submit_factcheck"].handler({"claims": [   # grading the brief is not a claim
            {"quote": "Caption contains zero numbers", "claim": "no numbers", "verdict": "UNSOURCED", "sources": [], "evidence": "-"}]})
        r = await tools["submit_factcheck"].handler({"claims": [
            {"quote": "Founded in 2019", "claim": "Founded in 2019", "verdict": "TRUE", "sources": ["owner:request"], "evidence": "request"}]})
        assert not r.get("is_error"), r
    d, _, _ = make_dispatcher(_one_step("sales_script_writer", "caption", "Founded in 2019.", extra_scripts={
        ("fact_checker", "factcheck"): lazy_then_honest}))
    await d.handle_message(msg("caption: we were founded in 2019"))
    assert seen["lazy"].get("is_error") and "2019" in seen["lazy"]["content"][0]["text"]
    assert seen["meta"].get("is_error") and "word for word" in seen["meta"]["content"][0]["text"]
    assert task(d).status == "DELIVERED"


async def test_talent_via_chief_of_staff_still_waits_for_g1(make_dispatcher):
    async def atlas(tools, ctx):
        r = await tools["submit_contract"].handler({"objective": "new hire", "size": "M", "deliverables": [{"id": "D1", "description": "x"}],
                                                    "acceptance_criteria": [{"id": "1", "text": "t", "check": "automatic"}],
                                                    "departments": [{"department": "talent", "objective": "design a podcast editor",
                                                                     "acceptance_criteria": [{"id": "1", "text": "spec"}]}]})
        assert not r.get("is_error"), r
    d, runner, _ = make_dispatcher({("chief_of_staff", "contract"): atlas,
                                    ("talent_lead", "contract"): lambda tools, ctx: _noop()})
    await d.handle_message(InboundMessage("E1", OWNER, "D1", None, "we need a podcast editor hire", "1.0", None, True))
    await approve(d, "G1")
    with d.Session() as db:
        child = db.scalar(select(Task).where(Task.department == "talent"))
    assert child is not None and child.g1_approval_id is None               # not inherited: Rhea drafts, you approve
    assert ("talent_lead", "contract") in [(c["employee"], c["phase"]) for c in runner.calls]


async def _noop():
    return None


async def test_numbers_inside_links_are_not_claims(make_dispatcher):
    d, runner, _ = make_dispatcher(_one_step("sales_script_writer", "caption", "Read more at https://example.com/2024/05/sleep"))
    await d.handle_message(msg("caption linking the sleep article"))
    assert task(d).status == "DELIVERED"          # default Proof ([] claims) accepted: no number to cover
