"""Org v2: show isolation (I1–I7), Proof (fact checker), Talent hire flow, research → write chains."""
import re
import subprocess
import sys

import yaml
from sqlalchemy import select

from workforce.slack import InboundMessage
from tests.test_flags import OWNER, approve, delivery_any, msg, ref_of, task, writer
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
    studio, sales = cfg.employee("studio_lead"), cfg.employee("sales_lead")
    d = lambda who, tt: {**BASE, "deliverables": [{"id": "D1", "assignee": who, "task_type": tt}]}   # noqa: E731
    assert not validate_contract(d("studio_builder", "jai_reel"), studio, cfg, show="jai")
    # Frame serves every show, but each route is bound to its show: no Sherlock reel on a Jai task
    assert any("only for ['sherlock']" in p for p in validate_contract(d("studio_builder", "sherlock_reel"), studio, cfg, show="jai"))
    # no show named -> a show route can't run
    assert any("no show" in p for p in validate_contract(d("studio_builder", "jai_reel"), studio, cfg, show=None))
    # a show-bound employee stays on its own show
    assert any("only on the 'sherlock' show" in p
               for p in validate_contract(d("show_sherlock_writer", "sherlock_script"), sales, cfg, show="jai"))
    # employees not shared into shows are barred from a show task (Apply holds your CV)
    assert any("doesn't work on show tasks" in p
               for p in validate_contract(d("sales_applications", "cover_letter"), sales, cfg, show="jai"))
    # shared helpers: Spark on any show; Voice's captions only for Jai/Football, never Sherlock's
    assert not validate_contract(d("sales_ideas", "generate_ideas"), sales, cfg, show="striker")
    assert not validate_contract(d("sales_writer", "caption"), sales, cfg, show="jai")
    assert any("only for ['jai', 'striker']" in p for p in validate_contract(d("sales_writer", "caption"), sales, cfg, show="sherlock"))


def test_I1_show_detection(cfg):
    assert cfg.shows_named("make a jai reel about coffee") == ["jai"]
    assert cfg.shows_named("football video on ISL") == ["striker"]
    assert cfg.shows_named("jaipur trip vlog") == []                       # whole words only
    assert sorted(cfg.shows_named("a jai reel and a sherlock reel")) == ["jai", "sherlock"]
    assert cfg.shows_named("pitch email to Jai at Acme") == []             # a name is not a show
    assert cfg.shows_named("Jai Studios wants a pitch") == []
    assert cfg.shows_named("show: striker") == ["striker"]
    assert cfg.shows_named("hey jai, do one on black holes") == ["jai"]    # addressing the show by name
    assert cfg.shows_named("sherlock, explain transformers") == ["sherlock"]
    assert cfg.shows_named("make a reel for the app at work") == []        # a video is never the company lane
    assert cfg.shows_named("jai video about a company app that failed") == ["jai"]


async def test_I1_two_shows_in_one_message_asks_owner(make_dispatcher, runtimes):
    async def jai_contract(tools, ctx):
        assert "belongs to the show 'jai'" in ctx["system"]
        r = await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "reel", "assignee": "studio_builder", "task_type": "jai_reel"}]})
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
            {"id": "D1", "description": "reel", "assignee": "studio_builder", "task_type": "sherlock_reel"}]})
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
    assert '"studio_builder": {' in roster(jai) and '"studio_designer": {' in roster(jai)
    sam = cfg.employee("sales_lead")
    sj, sn = system_prompt(cfg, sam, "contract", show="jai"), system_prompt(cfg, sam, "contract", show=None)
    assert '"sales_writer": {' in roster(sj) and '"sales_ideas": {' in roster(sj)
    assert '"show_sherlock_writer": {' not in roster(sj) and '"sales_applications": {' not in roster(sj)
    assert '"sales_applications": {' in roster(sn) and '"show_sherlock_writer": {' not in roster(sn)
    assert '"studio_builder": {' in roster(none)   # Studio's three also take a task that names no show


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
        t_jai = Task(id="tj", department="studio", requested_by=OWNER, original_request="x", show="jai")
        t_none = Task(id="tn", department="sales", requested_by=OWNER, original_request="x")
        db.add_all([t_jai, t_none])
        db.flush()
        frame, spark, sher_writer = cfg.employee("studio_builder"), cfg.employee("sales_ideas"), cfg.employee("show_sherlock_writer")
        m1 = ms.submit_candidate(db, frame, t_jai, "Jai reels open on a hard cut", layer="L3")
        m2 = ms.submit_candidate(db, frame, t_jai, "Jai signs off with 'peace'", layer="L1")
        m3 = ms.submit_candidate(db, spark, t_none, "Client Acme prefers short briefs", layer="L3")
        for m in (m1, m2, m3):
            m.status = "active"
        db.flush()
        assert m1.scope_id == "studio_builder@jai" and m2.scope_id == "show:jai" and m3.scope_id == "sales_ideas"
        read = lambda e, show=None: {m.id for m in ms.read(db, e, "", show=show)}   # noqa: E731
        assert m1.id in read(frame, "jai") and m1.id not in read(frame, "sherlock") and m1.id not in read(frame)
        assert m2.id in read(frame, "jai") and m2.id not in read(frame, "striker") and m2.id not in read(sher_writer)
        assert m2.id not in read(cfg.employee("sales_writer"))               # a show rule never reaches a non-show task
        assert m3.id not in read(spark, "jai") and m3.id in read(spark)        # general memory stays off show tasks


async def test_I3_standing_rule_on_show_task_is_scoped_to_show(make_dispatcher):
    d, _, _ = make_dispatcher({})
    await d.handle_message(msg("sherlock reels: always open with a deduction", channel="#studio"))
    with d.Session() as db:
        m = db.scalar(select(MemoryEntry).where(MemoryEntry.standing.is_(True)))
    assert m.scope_id == "show:sherlock"


# ------------------------------------------------------------------ I5 voice + show bible belong to one show
def test_I5_voice_belongs_to_the_task_show(cfg, Session):
    p = Policy(cfg)
    frame = cfg.employee("studio_builder")
    with Session() as db:
        tasks = {sh: Task(id=f"tv{sh}", department="studio", requested_by=OWNER, original_request="x", show=sh)
                 for sh in ("jai", "sherlock", "striker")}
        db.add_all(tasks.values())
        db.flush()
        ok = lambda show, voice: p.check(db, frame, "voice.synthesize", {"voice": voice}, tasks[show]).outcome   # noqa: E731
        assert ok("sherlock", "base") == ALLOW                 # Sherlock: Kokoro bm_lewis
        assert ok("jai", "base") == DENY and ok("striker", "base") == DENY   # you record Jai + Football
        assert ok("jai", "owner_clone") == DENY and ok("sherlock", "owner_clone") == DENY   # no cloning anywhere
        assert p.check(db, cfg.employee("show_sherlock_writer"), "voice.synthesize", {"voice": "base"},
                       tasks["sherlock"]).outcome == DENY      # writers hold no voice tool


def test_I5_show_bible_and_training_only_in_own_prompt(cfg, monkeypatch, runtimes):
    monkeypatch.setattr(cfg, "show_bible", lambda s: f"BIBLE-OF-{s}")
    pixel_jai = system_prompt(cfg, cfg.employee("studio_designer"), "execute", resolve(cfg, "studio_designer", "jai_visual"), show="jai")
    pixel_sher = system_prompt(cfg, cfg.employee("studio_designer"), "execute", show="sherlock")
    sher = system_prompt(cfg, cfg.employee("show_sherlock_writer"), "execute")
    assert "BIBLE-OF-jai" in pixel_jai and "BIBLE-OF-sherlock" not in pixel_jai     # shared Pixel: only this show's bible
    assert "BIBLE-OF-sherlock" in pixel_sher and "BIBLE-OF-jai" not in pixel_sher
    assert "BIBLE-OF-sherlock" in sher and "BIBLE-OF-jai" not in sher
    assert "`studio_designer`" in pixel_jai and "`studio_designer`" not in sher     # training file: own prompt only


def test_I5_placeholder_bible_means_stop_and_ask(cfg):
    sp = system_prompt(cfg, cfg.employee("show_sherlock_writer"), "execute")
    assert "/sherlock skill is this show's bible" in sp and "TODO (owner)" not in sp
    px = system_prompt(cfg, cfg.employee("studio_designer"), "execute", show="striker")
    assert "/football-video skill is this show's bible" in px and "TODO (owner)" not in px


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
def test_builders_and_posters_need_upstream(cfg, runtimes):
    maya = cfg.employee("studio_lead")
    contract = {**BASE, "deliverables": [{"id": "D1", "assignee": "studio_builder", "task_type": "sherlock_reel"},
                                         {"id": "D2", "assignee": "studio_poster", "task_type": "post_reel"}]}
    reel = {"deliverable": "D1", "to": "studio_builder", "task_type": "sherlock_reel", "objective": "o", "criteria": ["1"]}
    post = {"deliverable": "D2", "to": "studio_poster", "task_type": "post_reel", "objective": "o", "criteria": ["1"]}
    _, prob = validate_plan(cfg, maya, "t", contract, 1, "M", [reel, post], "sherlock")
    assert any("show_sherlock_writer" in p for p in prob)              # Frame never writes its own Sherlock script
    contract["_dept_inputs"] = ["artifact://t/X-sales-T1-script.md"]
    contract["_dept_input_authors"] = {"artifact://t/X-sales-T1-script.md": "show_sherlock_writer"}
    _, prob = validate_plan(cfg, maya, "t", contract, 1, "M", [{**reel, "inputs": ["artifact://t/X-sales-T1-script.md"]},
                                                             {**post, "inputs_from": ["T1"]}], "sherlock")
    assert prob == []
    _, prob = validate_plan(cfg, maya, "t", contract, 1, "M", [{**reel, "inputs": ["artifact://t/X-sales-T1-script.md"]}, post],
                            "sherlock")
    assert any("studio_builder" in p for p in prob)                    # Post only posts a reel Frame rendered


async def test_show_reel_script_comes_from_the_shows_own_writer(make_dispatcher, render_stub):
    """'sherlock reel' in #studio -> Sales child task (inherits show sherlock) -> Spark -> Sherlock-Writer -> Frame."""
    calls = {"plan": 0}

    async def maya_contract(tools, ctx):
        r = await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "reel", "assignee": "studio_builder", "task_type": "sherlock_reel"}]})
        assert not r.get("is_error"), r

    async def maya_plan(tools, ctx):
        calls["plan"] += 1
        if calls["plan"] == 1:
            r = await tools["submit_plan"].handler({"cross_dept": [{"department": "sales", "objective": "sherlock script on context windows",
                                                                    "acceptance_criteria": [{"id": "1", "text": "script"}]}]})
            assert not r.get("is_error"), r
            return
        ref = re.findall(r"artifact://\S+?X-sales-T2[\w.-]+", ctx["prompt"])[0].rstrip('",')
        ideas = re.findall(r"artifact://\S+?X-sales-T1[\w.-]+", ctx["prompt"])[0].rstrip('",')
        bad = await tools["submit_plan"].handler({"handoffs": [{"deliverable": "D1", "to": "studio_builder",
                                                                "task_type": "sherlock_reel", "objective": "reel", "criteria": ["1"], "inputs": [ideas]}]})
        assert bad.get("is_error") and "show_sherlock_writer" in bad["content"][0]["text"]   # ideas alone aren't a script
        r = await tools["submit_plan"].handler({"handoffs": [{"deliverable": "D1", "to": "studio_builder",
                                                              "task_type": "sherlock_reel", "objective": "reel", "criteria": ["1"], "inputs": [ref]}]})
        assert not r.get("is_error"), r

    async def sam_plan(tools, ctx):
        roster = ctx["system"].split("# Your specialists available")[1]
        assert '"show_sherlock_writer": {' in roster and '"sales_applications": {' not in roster
        bad = await tools["submit_plan"].handler({"handoffs": [
            {"to": "sales_ideas", "task_type": "generate_ideas", "objective": "r", "criteria": ["1"]},
            {"to": "sales_writer", "task_type": "caption", "objective": "s", "criteria": ["1"], "inputs_from": ["T1"]}]})
        assert bad.get("is_error") and "only for ['jai', 'striker']" in bad["content"][0]["text"]   # Voice never writes Sherlock
        r = await tools["submit_plan"].handler({"handoffs": [
            {"to": "sales_ideas", "task_type": "generate_ideas", "objective": "r", "criteria": ["1"]},
            {"to": "show_sherlock_writer", "task_type": "sherlock_script", "objective": "s", "criteria": ["1"], "inputs_from": ["T1"]}]})
        assert not r.get("is_error"), r

    d, runner, _ = make_dispatcher({
        ("studio_lead", "contract"): maya_contract, ("studio_lead", "plan"): maya_plan,
        ("sales_lead", "plan"): sam_plan,
        ("sales_ideas", "execute"): writer("Idea: why models forget the start of long chats."),
        ("show_sherlock_writer", "execute"): writer("Elementary: the window is full, so the oldest words fall out."),
        ("studio_builder", "execute"): writer("render placeholder")})
    await d.handle_message(msg("sherlock reel about context windows", channel="#studio"))
    await approve(d, "G1")
    with d.Session() as db:
        child = db.scalar(select(Task).where(Task.parent_id.is_not(None)))
        assert child.show == "sherlock" and child.status == "DELIVERED"             # sub-task inherits the show
        g4 = db.scalar(select(Approval).where(Approval.task_id == child.id, Approval.gate == "G4"))
    await d.on_approval(OWNER, g4.id, True)
    assert task(d).status == "DELIVERED"
    execs = [c["employee"] for c in runner.calls if c["phase"] == "execute"]
    assert execs == ["sales_ideas", "show_sherlock_writer", "studio_builder"]


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
    d, runner, slack = make_dispatcher(_one_step("sales_writer", "post_copy", "", extra_scripts={
        ("fact_checker", "factcheck"): proof, ("sales_writer", "execute"): script}))
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
                    plan=[{"to": "sales_applications", "task_type": "job_application"}]))
        db.commit()
    from workforce.harness import task_dir
    (task_dir("tp") / "artifacts").mkdir(parents=True)
    (task_dir("tp") / "artifacts" / "T1-cv.md").write_text("CV")
    await d.factcheck("tp")
    call = [c for c in runner.calls if c["phase"] == "factcheck"][-1]
    assert call["builtins"] == {}                                         # no WebSearch / WebFetch at all


def test_pii_allowed_only_where_contact_details_belong(cfg):
    assert "pii_absent" not in resolve(cfg, "sales_applications", "job_application").checks
    assert "pii_absent" not in resolve(cfg, "ops_bookkeeper", "invoice").checks
    assert "pii_absent" in resolve(cfg, "sales_writer", "pitch_email").checks


# ------------------------------------------------------------------ Talent
async def test_recruit_goes_from_atlas_to_office_and_is_filed_not_applied(make_dispatcher, tmp_path, monkeypatch, cfg):
    """Atlas recruits: his approved contract sends a brief to the office desk (no lead — planned in code),
    Mason writes the spec, Vera grades it, and on your G4 it is FILED as a proposal; only /wf hire makes it live."""
    spec = {"id": "studio_podcast_editor", "name": "Echo", "department": "studio", "kind": "specialist",
            "does": ["edit podcasts"], "does_not": ["publish"], "fire_when": "you ask for a podcast edit",
            "tools": ["workspace.read", "workspace.write", "submit_return"], "max_tier": "R1",
            "personality": {"voice": ["calm"]}, "routes": [{"task_type": "podcast_edit", "run": [], "checks": ["spellcheck"]}],
            "context": "Role: edits podcasts", "probation_tasks": ["a", "b", "c"], "pitch": "Meet Echo."}

    async def atlas(tools, ctx):
        r = await tools["submit_contract"].handler({"objective": "new hire", "size": "M", "deliverables": [{"id": "D1", "description": "x"}],
                                                    "acceptance_criteria": [{"id": "1", "text": "t", "check": "automatic"}],
                                                    "departments": [{"department": "office", "objective": "design a podcast editor",
                                                                     "acceptance_criteria": [{"id": "1", "text": "valid spec"}]}]})
        assert not r.get("is_error"), r

    async def mason(tools, ctx):
        ref = ref_of(await tools["workspace_write"].handler({"name": "spec.yaml", "content": yaml.safe_dump(spec)}))
        r = await tools["submit_return"].handler({"status": "done", "outputs": [ref], "confidence": 0.9,
                                                  "self_check": [{"criterion_id": "1", "result": "met", "evidence": "valid"}]})
        assert not r.get("is_error"), r
    monkeypatch.setattr(cfg, "dir", tmp_path / "config")
    d, runner, _ = make_dispatcher({("chief_of_staff", "contract"): atlas, ("office_architect", "execute"): mason})
    await d.handle_message(InboundMessage("E1", OWNER, "D1", None, "we need a podcast editor hire", "1.0", None, True))
    assert ("office_architect", "execute") not in [(c["employee"], c["phase"]) for c in runner.calls]   # waits for your G1
    await approve(d, "G1")
    with d.Session() as db:
        child = db.scalar(select(Task).where(Task.department == "office"))
        assert child.status == "DELIVERED" and child.plan[0]["to"] == "office_architect"
        g4 = db.scalar(select(Approval).where(Approval.task_id == child.id, Approval.gate == "G4"))
    phases = [(c["employee"], c["phase"]) for c in runner.calls]
    assert ("office_architect", "execute") in phases and ("verifier", "verify") in phases
    assert not any(e == "office" or p == "plan" and e not in ("chief_of_staff",) for e, p in phases)   # no lead, no plan call
    await d.on_approval(OWNER, g4.id, True)
    assert (tmp_path / "proposals").is_dir() and list((tmp_path / "proposals").glob("*.yaml"))
    assert "studio_podcast_editor" not in (ROOT / "config/org.yaml").read_text()      # live config untouched


async def test_lex_overflow_report_reaches_atlas(make_dispatcher):
    d, runner, _ = make_dispatcher({})
    with d.Session() as db:
        db.add_all([MemoryEntry(id=f"o{i}", layer="L3", scope_id="studio_builder@jai", kind="feedback", source="t",
                                author="x", status="active", content="x" * 300) for i in range(9)])
        db.commit()
        over = d.memory.overflowing(db)
    assert [o["scope"] for o in over] == ["studio_builder@jai"] and over[0]["pct"] >= 0.8
    [tid] = await d.report_overflow(over)
    with d.Session() as db:
        t = db.get(Task, tid)
        assert t.department == "hq" and "Frame's memory for jai" in t.original_request
    assert ("chief_of_staff", "contract") in [(c["employee"], c["phase"]) for c in runner.calls]


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
                {"routes": [{"task_type": "post_copy", "run": [], "checks": ["spellcheck"]}]}, {"probation_tasks": ["1"]},
                {"tools": ["web.fetch", "finance.read_uploads"]}):
        f.write_text(yaml.safe_dump({**good, **bad}))
        assert check_main(["employee_spec", str(f)]) == 1, bad


async def test_owner_can_undo_a_wrong_show_detection(make_dispatcher):
    async def c(tools, ctx):
        await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "x", "assignee": "sales_ideas", "task_type": "generate_ideas"}]})
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
    d, _, _ = make_dispatcher(_one_step("sales_writer", "post_copy", "Founded in 2019.", extra_scripts={
        ("fact_checker", "factcheck"): lazy_then_honest}))
    await d.handle_message(msg("caption: we were founded in 2019"))
    assert seen["lazy"].get("is_error") and "2019" in seen["lazy"]["content"][0]["text"]
    assert seen["meta"].get("is_error") and "word for word" in seen["meta"]["content"][0]["text"]
    assert task(d).status == "DELIVERED"


async def _noop():
    return None


async def test_numbers_inside_links_are_not_claims(make_dispatcher):
    d, runner, _ = make_dispatcher(_one_step("sales_writer", "post_copy", "Read more at https://example.com/2024/05/sleep"))
    await d.handle_message(msg("caption linking the sleep article"))
    assert task(d).status == "DELIVERED"          # default Proof ([] claims) accepted: no number to cover


async def test_lead_with_nobody_fitting_sends_a_recruit_brief(make_dispatcher, tmp_path, monkeypatch, cfg):
    """Maya can't do a podcast: her contract carries `recruit`, you approve, Mason designs the hire at the
    office desk, and the task closes once you accept the proposal (it goes live only with /wf hire)."""
    spec = {"id": "studio_podcast_editor", "name": "Echo", "department": "studio", "kind": "specialist",
            "does": ["edit podcasts"], "does_not": ["publish"], "fire_when": "you ask for a podcast edit",
            "tools": ["workspace.read", "workspace.write", "submit_return"], "max_tier": "R1",
            "personality": {"voice": ["calm"]}, "routes": [{"task_type": "podcast_edit", "run": [], "checks": ["spellcheck"]}],
            "context": "Role: edits podcasts", "probation_tasks": ["a", "b", "c"], "pitch": "Meet Echo."}

    async def maya(tools, ctx):
        bad = await tools["submit_contract"].handler({"objective": "podcast", "size": "S", "deliverables": [],
                                                      "acceptance_criteria": [{"id": "1", "text": "t", "check": "automatic"}]})
        assert bad.get("is_error") and "recruit" in bad["content"][0]["text"]
        r = await tools["submit_contract"].handler({"objective": "podcast", "size": "S", "deliverables": [],
                                                    "recruit": "a podcast editor for my weekly episode",
                                                    "acceptance_criteria": [{"id": "1", "text": "t", "check": "automatic"}]})
        assert not r.get("is_error"), r

    async def mason(tools, ctx):
        assert "podcast editor" in ctx["prompt"]
        ref = ref_of(await tools["workspace_write"].handler({"name": "spec.yaml", "content": yaml.safe_dump(spec)}))
        await tools["submit_return"].handler({"status": "done", "outputs": [ref], "confidence": 0.9,
                                              "self_check": [{"criterion_id": "1", "result": "met", "evidence": "valid"}]})
    monkeypatch.setattr(cfg, "dir", tmp_path / "config")
    d, runner, _ = make_dispatcher({("studio_lead", "contract"): maya, ("office_architect", "execute"): mason})
    await d.handle_message(msg("edit my weekly podcast episode", channel="#studio"))
    assert task(d).status == "CONTRACT_DRAFTED"            # S, but a recruit always waits for your G1
    await approve(d, "G1")
    with d.Session() as db:
        child = db.scalar(select(Task).where(Task.department == "office"))
        g4 = db.scalar(select(Approval).where(Approval.task_id == child.id, Approval.gate == "G4"))
    assert child.status == "DELIVERED" and ("studio_lead", "plan") not in [(c["employee"], c["phase"]) for c in runner.calls]
    await d.on_approval(OWNER, g4.id, True)
    assert list((tmp_path / "proposals").glob("*.yaml"))
    assert task(d).status == "DELIVERED"                   # the studio task closes with the proposal filed
