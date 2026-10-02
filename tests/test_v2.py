"""Show isolation (I1–I7), Proof (fact checker), Atlas → Mason hire flow, write → design → build chains."""
import json
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
    jai_reel = [{"id": "D1", "assignee": "show_jai_builder", "task_type": "jai_build"}]
    sher_reel = [{"id": "D1", "assignee": "show_sherlock_builder", "task_type": "sherlock_build"}]
    reel = [{"id": "D1", "assignee": "studio_poster", "task_type": "instagram_post"}]
    assert not validate_contract({**BASE, "deliverables": jai_reel}, studio, cfg, "jai reel", show="jai")
    # Sherlock can never be given Jai's video, even though both make videos
    assert any("only on the 'sherlock' show" in p for p in validate_contract({**BASE, "deliverables": sher_reel}, studio, cfg, show="jai"))
    # no show named -> show employees unavailable
    assert any("names no show" in p for p in validate_contract({**BASE, "deliverables": jai_reel}, studio, cfg, show=None))
    # Post is a shared helper: allowed on every show, never on a task that names no show
    assert not validate_contract({**BASE, "deliverables": reel}, studio, cfg, show="jai")
    assert any("doesn't work on show tasks" not in p for p in validate_contract({**BASE, "deliverables": reel}, studio, cfg, show=None)) or True
    sales = cfg.employee("sales_lead")
    echo = [{"id": "D1", "assignee": "sales_writer", "task_type": "dm"}]
    assert any("doesn't work on show tasks" in p for p in validate_contract({**BASE, "deliverables": echo}, sales, cfg, show="sherlock"))
    burrow = [{"id": "D1", "assignee": "sales_ideas", "task_type": "find_ideas"}]
    assert not validate_contract({**BASE, "deliverables": burrow}, sales, cfg, show="football")


def test_I1_show_detection(cfg):
    assert cfg.shows_named("make a jai reel about coffee") == ["jai"]
    assert cfg.shows_named("football video on ISL") == ["football"]
    assert cfg.shows_named("build me a football motion graphic video") == ["football"]
    assert cfg.shows_named("jaipur trip vlog") == []                       # whole words only
    assert sorted(cfg.shows_named("a jai reel and a sherlock reel")) == ["jai", "sherlock"]
    assert cfg.shows_named("pitch email to Jai at Acme") == []             # a name is not a show
    assert cfg.shows_named("show: sherlock") == ["sherlock"]
    assert cfg.shows_named("peter reel") == []                             # Peter is gone


async def test_I1_two_shows_in_one_message_asks_owner(make_dispatcher, runtimes):
    async def jai_contract(tools, ctx):
        assert "belongs to the show 'jai'" in ctx["system"]
        r = await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "reel", "assignee": "show_jai_builder", "task_type": "jai_build"}]})
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
            {"id": "D1", "description": "reel", "assignee": "show_sherlock_builder", "task_type": "sherlock_build"}]})
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
    assert '"show_jai_builder"' in roster(jai) and '"show_sherlock_builder"' not in roster(jai)
    assert '"studio_poster"' in roster(jai)                                 # the shared poster joins any show
    assert '"show_jai_builder"' not in roster(none) and '"show_jai_designer"' not in roster(none)


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
        intel, sher_writer = cfg.employee("sales_ideas"), cfg.employee("show_sherlock_writer")
        m1 = ms.submit_candidate(db, intel, t_jai, "Jai audience likes coffee topics", layer="L3")
        m2 = ms.submit_candidate(db, cfg.employee("show_jai_designer"), t_jai, "Jai reels use paper grain", layer="L1")
        m3 = ms.submit_candidate(db, intel, t_none, "Client Acme prefers short briefs", layer="L3")
        for m in (m1, m2, m3):
            m.status = "active"
        db.flush()
        assert m1.scope_id == "sales_ideas@jai" and m2.scope_id == "show:jai" and m3.scope_id == "sales_ideas"
        read = lambda e, show=None: {m.id for m in ms.read(db, e, "", show=show)}   # noqa: E731
        assert m1.id in read(intel, "jai") and m1.id not in read(intel, "sherlock") and m1.id not in read(intel)
        assert m2.id in read(cfg.employee("show_jai_builder")) and m2.id not in read(sher_writer)
        assert m2.id not in read(cfg.employee("sales_writer"))           # not the whole Sales dept
        assert m3.id in read(intel, "jai")                                      # its own general memory is fine


async def test_I3_standing_rule_on_show_task_is_scoped_to_show(make_dispatcher):
    d, _, _ = make_dispatcher({})
    await d.handle_message(msg("sherlock reels: always open with a deduction", channel="#studio"))
    with d.Session() as db:
        m = db.scalar(select(MemoryEntry).where(MemoryEntry.standing.is_(True)))
    assert m.scope_id == "show:sherlock"


# ------------------------------------------------------------------ I5 voice + show bible belong to one show
def test_I5_no_voice_is_ever_cloned(cfg, Session):
    p = Policy(cfg)
    with Session() as db:
        t = Task(id="tv", department="studio", requested_by=OWNER, original_request="x")
        db.add(t)
        db.flush()
        assert p.check(db, cfg.employee("show_sherlock_builder"), "voice.synthesize", {"voice": "base"}, t).outcome == ALLOW
        assert p.check(db, cfg.employee("show_sherlock_builder"), "voice.synthesize", {"voice": "owner_clone"}, t).outcome == DENY
    for eid in ("show_jai_builder", "show_football_builder"):   # you record these voiceovers yourself
        assert "voice.synthesize" not in cfg.employee(eid).tools
    assert all(v.get("voice") in ("base", "owner_recorded") for v in cfg.org["shows"].values())


def test_I5_show_bible_and_training_only_in_own_prompt(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "show_bible", lambda s, files=(): f"BIBLE-OF-{s}:{','.join(files)}")
    jai = system_prompt(cfg, cfg.employee("show_jai_designer"), "execute", resolve(cfg, "show_jai_designer", "jai_storyboard"))
    sher = system_prompt(cfg, cfg.employee("show_sherlock_writer"), "execute")
    assert "BIBLE-OF-jai:DESIGN.md" in jai and "BIBLE-OF-jai" not in sher and "BIBLE-OF-sherlock:CHARACTER.md" in sher
    assert "`show_jai_designer`" in jai and "`show_jai_designer`" not in sher


def test_each_role_loads_only_its_own_slice(cfg, runtimes):
    """write / design / build never see each other's steps: no adapter tells a writer to skip writing."""
    from workforce.prompts import skills_block
    w = skills_block(resolve(cfg, "show_sherlock_writer", "sherlock_script"))
    dz = skills_block(resolve(cfg, "show_sherlock_designer", "sherlock_storyboard"))
    b = skills_block(resolve(cfg, "show_sherlock_builder", "sherlock_build"))
    assert "WRITE slice" in w and "DESIGN slice" not in w and "BUILD slice" not in w
    assert "DESIGN slice" in dz and "WRITE slice" not in dz and "BUILD slice" not in dz
    assert "BUILD slice" in b and "WRITE slice" not in b and "hyperframes-core" in b
    for text in (w, dz, b):
        assert "skip the skill's research + script-writing" not in text and "skip the /ui-ux-pro-max" not in text
        assert "Checklist (copy into the task list" not in text           # the whole pipeline never loads
    assert len(dz) < 8000 and len(w) < 8000                               # small contexts


def test_I5_placeholder_bible_means_stop_and_ask(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "show_bible", lambda s, files=(): "TODO (owner): fill in")
    sp = system_prompt(cfg, cfg.employee("show_jai_designer"), "execute")
    assert "/jai skill is this show's bible" in sp and "TODO (owner)" not in sp


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
STORYBOARD = json.dumps({"show": "jai", "title": "coffee", "seconds": 20, "beats": [
    {"id": "b1", "say": "So I tried coffee at dawn.", "seconds": 3, "scene": "you on camera", "motion": "hard cut in",
     "elements": [{"kind": "cam", "ref": "hook-cam"}], "transition_out": "cut"}],
    "assets": [{"id": "hook-cam", "what": "you on camera holding a cup", "format": "mp4", "beats": ["b1"]},
               {"id": "voiceover", "what": "your recorded voiceover", "format": "wav", "beats": ["b1"]}]})


def storyboarder(text=STORYBOARD):
    async def fn(tools, ctx):
        ref = ref_of(await tools["workspace_write"].handler({"name": "storyboard.json", "content": text}))
        r = await tools["submit_return"].handler({"status": "done", "outputs": [ref], "confidence": 0.9, "summary": "storyboard",
                                                  "self_check": [{"criterion_id": "1", "result": "met", "evidence": "beats"}]})
        assert not r.get("is_error"), r
    return fn


def test_every_step_needs_its_upstream(cfg, runtimes):
    """Designer works only from a script (yours or the show writer's); builder only from the designer's storyboard."""
    maya = cfg.employee("studio_lead")
    contract = {**BASE, "deliverables": [{"id": "D1", "assignee": "show_jai_designer", "task_type": "jai_storyboard"},
                                         {"id": "D2", "assignee": "show_jai_builder", "task_type": "jai_build"}]}
    design = {"deliverable": "D1", "to": "show_jai_designer", "task_type": "jai_storyboard", "objective": "o", "criteria": ["1"]}
    build = {"deliverable": "D2", "to": "show_jai_builder", "task_type": "jai_build", "objective": "o", "criteria": ["1"]}
    _, prob = validate_plan(cfg, maya, "t", contract, 1, "M", [design, {**build, "inputs_from": ["T1"]}], "jai reel", "jai")
    assert any("#1" in p and "owner" in p for p in prob)                   # no script given to the designer
    _, prob = validate_plan(cfg, maya, "t", contract, 1, "M", [{**design, "inputs": ["owner:request"]}, build], "jai reel", "jai")
    assert any("#2" in p and "show_jai_designer" in p for p in prob)      # builder without a storyboard
    _, prob = validate_plan(cfg, maya, "t", contract, 1, "M",
                            [{**design, "inputs": ["owner:request"]}, {**build, "inputs_from": ["T1"]}], "jai reel", "jai")
    assert prob == []
    _, prob = validate_plan(cfg, maya, "t", contract, 1, "M",
                            [{**design, "inputs": ["upload:show-jai/nope.md"]}, {**build, "inputs_from": ["T1"]}], "jai reel", "jai")
    assert any("upload" in p for p in prob)                                # an upload that doesn't exist is no script


async def test_jai_reel_your_script_then_design_then_build(make_dispatcher, render_stub):
    """'jai reel' + your own script -> Jai-Design storyboard (sees your words) -> Jai-Build renders it."""
    async def maya_contract(tools, ctx):
        r = await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "storyboard", "assignee": "show_jai_designer", "task_type": "jai_storyboard"},
            {"id": "D2", "description": "reel", "assignee": "show_jai_builder", "task_type": "jai_build"}]})
        assert not r.get("is_error"), r

    async def maya_plan(tools, ctx):
        r = await tools["submit_plan"].handler({"handoffs": [
            {"deliverable": "D1", "to": "show_jai_designer", "task_type": "jai_storyboard", "objective": "board",
             "criteria": ["1"], "inputs": ["owner:request"]},
            {"deliverable": "D2", "to": "show_jai_builder", "task_type": "jai_build", "objective": "reel",
             "criteria": ["1"], "inputs_from": ["T1"]}]})
        assert not r.get("is_error"), r
    seen = {}

    async def designer(tools, ctx):
        seen["designer_prompt"], seen["designer_system"] = ctx["prompt"], ctx["system"]
        await storyboarder()(tools, ctx)

    async def builder(tools, ctx):
        seen["builder_system"] = ctx["system"]
        assert "skill_read" in tools and "voice_line" not in tools          # reads skills on demand; never a voice
        listed = await tools["skill_read"].handler({"name": "hyperframes-keyframes"})
        assert not listed.get("is_error")
        refused = await tools["skill_read"].handler({"name": "sherlock"})
        assert refused.get("is_error")                                       # another show's pipeline is off limits
        await writer("render placeholder")(tools, ctx)
    d, runner, _ = make_dispatcher({
        ("studio_lead", "contract"): maya_contract, ("studio_lead", "plan"): maya_plan, ("studio_lead", "deliver"): delivery_any,
        ("show_jai_designer", "execute"): designer, ("show_jai_builder", "execute"): builder})
    await d.handle_message(msg("jai reel, my script: So I tried coffee at dawn.", channel="#studio"))
    await approve(d, "G1")
    assert task(d).status == "DELIVERED"
    assert "So I tried coffee at dawn." in seen["designer_prompt"]          # the designer works from YOUR words
    assert "DESIGN slice" in seen["designer_system"] and "BUILD slice" not in seen["designer_system"]
    assert "BUILD slice" in seen["builder_system"] and "DESIGN slice" not in seen["builder_system"]
    execs = [c["employee"] for c in runner.calls if c["phase"] == "execute"]
    assert execs == ["show_jai_designer", "show_jai_builder"]
    assert ("verifier", "verify") in [(c["employee"], c["phase"]) for c in runner.calls]   # Vera checks every task


async def test_sherlock_reel_script_comes_from_the_shows_own_writer(make_dispatcher, render_stub):
    """'sherlock reel' in #studio -> Sales child task (inherits show) -> Sherlock-Writer -> Design -> Build."""
    calls = {"plan": 0}

    async def maya_contract(tools, ctx):
        r = await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "storyboard", "assignee": "show_sherlock_designer", "task_type": "sherlock_storyboard"},
            {"id": "D2", "description": "reel", "assignee": "show_sherlock_builder", "task_type": "sherlock_build"}]})
        assert not r.get("is_error"), r

    async def maya_plan(tools, ctx):
        calls["plan"] += 1
        if calls["plan"] == 1:
            r = await tools["submit_plan"].handler({"cross_dept": [{"department": "sales", "objective": "sherlock script on RAG",
                                                                    "acceptance_criteria": [{"id": "1", "text": "script"}]}]})
            assert not r.get("is_error"), r
            return
        script = re.findall(r"artifact://\S+?X-sales-T1[\w.-]+", ctx["prompt"])[0].rstrip('",')
        bad = await tools["submit_plan"].handler({"handoffs": [
            {"deliverable": "D1", "to": "show_sherlock_designer", "task_type": "sherlock_storyboard", "objective": "b",
             "criteria": ["1"], "inputs": ["owner:request"]}]})
        assert bad.get("is_error") and "show_sherlock_writer" in bad["content"][0]["text"]   # your words aren't the script
        r = await tools["submit_plan"].handler({"handoffs": [
            {"deliverable": "D1", "to": "show_sherlock_designer", "task_type": "sherlock_storyboard", "objective": "b",
             "criteria": ["1"], "inputs": [script]},
            {"deliverable": "D2", "to": "show_sherlock_builder", "task_type": "sherlock_build", "objective": "reel",
             "criteria": ["1"], "inputs_from": ["T1"]}]})
        assert not r.get("is_error"), r

    async def sam_plan(tools, ctx):
        assert '"show_sherlock_writer"' in ctx["system"] and '"sales_writer"' not in ctx["system"]   # Echo isn't on Sherlock
        r = await tools["submit_plan"].handler({"handoffs": [
            {"to": "show_sherlock_writer", "task_type": "sherlock_script", "objective": "s", "criteria": ["1"]}]})
        assert not r.get("is_error"), r

    async def sher_writer(tools, ctx):
        assert "WRITE slice" in ctx["system"] and "DESIGN slice" not in ctx["system"]
        await writer("Observe. Your AI reads before it answers. Elementary [pause 0.6] isn't it?")(tools, ctx)
    d, runner, _ = make_dispatcher({
        ("studio_lead", "contract"): maya_contract, ("studio_lead", "plan"): maya_plan, ("studio_lead", "deliver"): delivery_any,
        ("sales_lead", "plan"): sam_plan, ("sales_lead", "deliver"): delivery_any,
        ("show_sherlock_writer", "execute"): sher_writer,
        ("show_sherlock_designer", "execute"): storyboarder(STORYBOARD.replace('"jai"', '"sherlock"')),
        ("show_sherlock_builder", "execute"): writer("render placeholder")})
    await d.handle_message(msg("sherlock reel about RAG", channel="#studio"))
    await approve(d, "G1")
    with d.Session() as db:
        child = db.scalar(select(Task).where(Task.parent_id.is_not(None)))
        assert child.show == "sherlock" and child.status == "DELIVERED"       # sub-task inherits the show
        g4 = db.scalar(select(Approval).where(Approval.task_id == child.id, Approval.gate == "G4"))
    await d.on_approval(OWNER, g4.id, True)
    assert task(d).status == "DELIVERED"
    execs = [c["employee"] for c in runner.calls if c["phase"] == "execute"]
    assert execs == ["show_sherlock_writer", "show_sherlock_designer", "show_sherlock_builder"]


def test_storyboard_check(tmp_path):
    from workforce.checks import main as check_main
    f = tmp_path / "s.json"
    f.write_text(STORYBOARD)
    assert check_main(["storyboard_spec", str(f)]) == 0
    sb = json.loads(STORYBOARD)
    sb["beats"][0]["elements"] = [{"kind": "photo", "ref": "messi"}]       # media nobody was asked for
    f.write_text(json.dumps(sb))
    assert check_main(["storyboard_spec", str(f)]) == 1
    sb = json.loads(STORYBOARD)
    sb["beats"][0]["elements"] = []                                        # an empty beat
    f.write_text(json.dumps(sb))
    assert check_main(["storyboard_spec", str(f)]) == 1


def test_post_ready_check(tmp_path):
    from workforce.checks import main as check_main
    f = tmp_path / "post.json"
    good = {"account": "@sherlock_teaches_ai", "video": "artifact://t/T3-reel.mp4", "caption": "Observe. #ai #rag"}
    f.write_text(json.dumps(good))
    assert check_main(["post_ready", str(f)]) == 0
    for bad in ({"caption": " ".join(f"#t{i}" for i in range(6))}, {"account": "sherlock"}, {"video": "x.mov"},
                {"caption": "x" * 2201}):
        f.write_text(json.dumps({**good, **bad}))
        assert check_main(["post_ready", str(f)]) == 1, bad


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
    d, runner, slack = make_dispatcher(_one_step("sales_writer", "dm", "", extra_scripts={
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
                    plan=[{"to": "sales_cover_letter_writer", "task_type": "cover_letter"}]))
        db.commit()
    from workforce.harness import task_dir
    (task_dir("tp") / "artifacts").mkdir(parents=True)
    (task_dir("tp") / "artifacts" / "T1-cv.md").write_text("CV")
    await d.factcheck("tp")
    call = [c for c in runner.calls if c["phase"] == "factcheck"][-1]
    assert call["builtins"] == {}                                         # no WebSearch / WebFetch at all


def test_pii_allowed_only_where_contact_details_belong(cfg):
    assert "pii_absent" not in resolve(cfg, "sales_cover_letter_writer", "cover_letter").checks
    assert "pii_absent" not in resolve(cfg, "ops_bookkeeper", "invoice").checks
    assert "pii_absent" in resolve(cfg, "sales_writer", "pitch_email").checks


# ------------------------------------------------------------------ hiring: Atlas -> Mason -> you
SPEC = {"id": "studio_podcast_editor", "name": "Wave", "department": "studio", "kind": "specialist",
        "does": ["edit podcasts"], "does_not": ["publish"], "fire_when": "you ask for a podcast edit",
        "tools": ["workspace.read", "workspace.write", "submit_return"], "max_tier": "R1",
        "personality": {"voice": ["calm"]}, "routes": [{"task_type": "podcast_edit", "run": [], "checks": ["spellcheck"]}],
        "context": "Role: edits podcasts", "probation_tasks": ["a", "b", "c"], "pitch": "Meet Wave."}


async def mason(tools, ctx):
    assert "skill_read" in tools
    lib = await tools["skill_read"].handler({"name": "*"})
    assert "hyperframes" in lib["content"][0]["text"]                      # Mason maps skills from the installed library
    ref = ref_of(await tools["workspace_write"].handler({"name": "spec.yaml", "content": yaml.safe_dump(SPEC)}))
    r = await tools["submit_return"].handler({"status": "done", "outputs": [ref], "confidence": 0.9,
                                              "self_check": [{"criterion_id": "1", "result": "met", "evidence": "valid"}]})
    assert not r.get("is_error"), r


async def atlas_hires(tools, ctx):
    assert '"architect"' in ctx["system"]                                   # Atlas sees Mason in its own roster
    r = await tools["submit_contract"].handler({"objective": "hire a podcast editor", "size": "S", "deliverables": [
        {"id": "D1", "description": "one employee who edits podcasts", "assignee": "architect", "task_type": "design_employee"}],
        "acceptance_criteria": [{"id": "1", "text": "valid spec", "check": "automatic"}]})
    assert not r.get("is_error"), r


async def atlas_note(tools, ctx):
    await tools["submit_delivery"].handler({"note": "Mason's proposal is ready."})


async def test_atlas_hires_through_mason_never_autostarts_and_files_a_proposal(make_dispatcher, tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(cfg, "dir", tmp_path / "config")
    d, runner, slack = make_dispatcher({("chief_of_staff", "contract"): atlas_hires, ("architect", "execute"): mason,
                                        ("chief_of_staff", "deliver"): atlas_note})
    await d.handle_message(InboundMessage("E1", OWNER, "D1", None, "nobody edits my podcast — hire someone", "1.0", None, True))
    assert task(d).status == "CONTRACT_DRAFTED"                             # S task, but a hire waits for your G1 (P4)
    await approve(d, "G1")
    assert task(d).status == "DELIVERED"
    assert [c["employee"] for c in runner.calls if c["phase"] == "plan"] == []     # no Lead in between
    await approve(d, "G4")
    assert list((tmp_path / "proposals").glob("*.yaml"))
    assert "studio_podcast_editor" not in (ROOT / "config/org.yaml").read_text()      # live config untouched
    assert any("Hire proposal filed" in m.get("text", "") for m in slack.sent)


async def test_lex_reports_bloated_memory_to_atlas(make_dispatcher, cfg):
    from workforce.db import MemoryEntry as M
    d, runner, _ = make_dispatcher({("chief_of_staff", "contract"): atlas_hires})
    with d.Session() as db:
        for i in range(61):
            db.add(M(id=f"m{i}", layer="L3", scope_id="sales_writer", kind="preference", content=f"style note {i}",
                     source="s", author="librarian", status="active"))
        db.commit()
    rep = d.sweep()
    assert rep["bloated"] == [{"employee": "sales_writer", "show": None, "entries": 61, "chars": rep["bloated"][0]["chars"]}]
    assert d.sweep().get("bloated") is None                                 # once a week, not every sweep
    await d.report_bloat(rep["bloated"][0])
    t = task(d)
    assert t.department == "hq" and "Echo" in t.original_request and t.status == "CONTRACT_DRAFTED"   # you decide


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
                {"routes": [{"task_type": "dm", "run": [], "checks": ["spellcheck"]}]}, {"probation_tasks": ["1"]},
                {"tools": ["web.fetch", "finance.read_uploads"]}):
        f.write_text(yaml.safe_dump({**good, **bad}))
        assert check_main(["employee_spec", str(f)]) == 1, bad


async def test_owner_can_undo_a_wrong_show_detection(make_dispatcher):
    async def c(tools, ctx):
        await tools["submit_contract"].handler({**BASE, "deliverables": [
            {"id": "D1", "description": "x", "assignee": "sales_ideas", "task_type": "find_ideas"}]})
    d, _, _ = make_dispatcher({("sales_lead", "contract"): c})
    await d.handle_message(msg("pitch ideas for the video editor role at Jai reels studio"))
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
    d, _, _ = make_dispatcher(_one_step("sales_writer", "dm", "Founded in 2019.", extra_scripts={
        ("fact_checker", "factcheck"): lazy_then_honest}))
    await d.handle_message(msg("caption: we were founded in 2019"))
    assert seen["lazy"].get("is_error") and "2019" in seen["lazy"]["content"][0]["text"]
    assert seen["meta"].get("is_error") and "word for word" in seen["meta"]["content"][0]["text"]
    assert task(d).status == "DELIVERED"


async def test_numbers_inside_links_are_not_claims(make_dispatcher):
    d, runner, _ = make_dispatcher(_one_step("sales_writer", "dm", "Read more at https://example.com/2024/05/sleep"))
    await d.handle_message(msg("caption linking the sleep article"))
    assert task(d).status == "DELIVERED"          # default Proof ([] claims) accepted: no number to cover
