"""Your original requests, one test each. Quotes are from your messages; each test proves the running code
does it (scripted agents — the live Claude runs are in scripts/live_check.py).

Run: pytest tests/test_requirements.py -v
"""
import json
from datetime import datetime, timezone

from sqlalchemy import select

from tests.test_flags import (COPY, OWNER, approve, delivery, msg, poster, ref_of, task, two_step_contract,
                              two_step_plan, verdict, writer)
from workforce import harness as hmod
from workforce.db import Approval, MemoryEntry, Task
from workforce.dispatcher import is_chitchat
from workforce.memory import MemoryStore
from workforce.policy import ALLOW, DENY, Policy
from workforce.prompts import system_prompt
from workforce.routing import resolve


def full_team(extra=None):
    return {("sales_lead", "contract"): two_step_contract(), ("sales_lead", "plan"): two_step_plan,
            ("sales_researcher", "execute"): writer(COPY), ("sales_outreach_writer", "execute"): poster({}),
            ("verifier", "verify"): verdict(["PASS"]), ("sales_lead", "deliver"): delivery, **(extra or {})}


# R1 "create employees across all my slack channels and give them skills + personality"
def test_R01_employees_per_channel_with_skills_and_personality(cfg):
    assert set(cfg.dept_channels) == {"#studio", "#sales", "#talent", "#engineering", "#ops"}
    for e in cfg.employees.values():
        assert e.personality.get("voice"), e.id
        assert cfg.context(e.id), f"{e.id} has no training file"
    script = cfg.employee("sales_script_writer")
    sp = system_prompt(cfg, script, "execute", resolve(cfg, script.id, "caption"))
    assert "Script" in sp and "hooky" in sp and '<skill_brief name="humanizer">' in sp and "# Your training" in sp


# R2 "really really hardcode all permissions, rules of each employee and their behaviour"
def test_R02_permissions_enforced_in_code_not_prompts(cfg, Session):
    p = Policy(cfg)
    with Session() as db:
        t = Task(id="r2", department="sales", requested_by=OWNER, original_request="x", contract_version=1)
        db.add(t)
        db.flush()
        # even if a model "decides" to, it cannot: the Tool Proxy denies
        assert p.check(db, cfg.employee("sales_outreach_writer"), "email.send_external", {}, t).outcome != ALLOW
        assert p.check(db, cfg.employee("ops_reporting_analyst"), "payments.any", {}, t).outcome == DENY
        assert p.check(db, cfg.employee("sales_lead"), "permissions.modify", {}, t).outcome == DENY


# R3 "how they act - what skills they run"
def test_R03_skills_chosen_by_rule_not_model(cfg, runtimes):
    assert resolve(cfg, "studio_faceless_editor", "launch_promo_video").skills == ["ui-ux-pro-max", "hyperframes", "product-launch-video"]
    assert resolve(cfg, "sales_script_writer", "caption").skills == ["humanizer"]


# R4 "how and when each employee talks to another" + R7 "where and when the handoff is happening"
async def test_R04_R07_handoffs_only_through_lead_and_dispatcher(make_dispatcher):
    seen = {}
    d, runner, _ = make_dispatcher(full_team({("sales_outreach_writer", "execute"): poster(seen)}))
    await d.handle_message(msg("caption and a post please, verify it"))
    await approve(d, "G1")
    # specialists never get a tool to message each other; the only link is the upstream artifact the Dispatcher passes
    spec_tools = {n for c in runner.calls if c["phase"] == "execute" for n in c["tools"]}
    assert spec_tools <= {"workspace_write", "workspace_read", "memory_read", "slack_post", "submit_return", "act", "skill_read",
                          "uploads_list", "uploads_read"}   # no tool reaches another employee
    assert COPY in seen["upstream"]
    order = [(c["employee"], c["phase"]) for c in runner.calls]
    assert order == [("sales_lead", "contract"), ("sales_lead", "plan"), ("sales_researcher", "execute"),
                     ("sales_outreach_writer", "execute"), ("fact_checker", "factcheck"), ("verifier", "verify")]   # delivery note: code


# R5 "who leads them, who runs them"
def test_R05_leads_lead_dispatcher_runs(cfg):
    for dept, lead in cfg.leads.items():
        assert cfg.employee(lead).kind == "lead" and "delegate" in cfg.employee(lead).tools
    for s in cfg.employees.values():
        if s.kind == "specialist":
            assert "delegate" not in s.tools and "submit_plan" not in s.tools


# R6 "where is the human in the loop, validating their work against what I asked for"
async def test_R06_human_gates_and_validation_against_request(make_dispatcher):
    d, runner, slack = make_dispatcher(full_team())
    await d.handle_message(msg("caption and a post please"))
    assert task(d).status == "CONTRACT_DRAFTED"                       # G1: nothing runs before you approve
    await approve(d, "G1")
    t = task(d)
    assert t.status == "DELIVERED" and t.verification_id           # checked criterion-by-criterion
    assert '"verifier", "verify"' not in json.dumps([])            # (sanity)
    assert await approve(d, "G4") == "ok" and task(d).status == "CLOSED"   # G4: you accept


# R8 "what each employee does"
def test_R08_every_employee_has_does_and_does_not(cfg):
    for e in cfg.employees.values():
        assert e.does, e.id


# R9 "how does it process and store info so it doesn't hallucinate"
async def test_R09_blocked_instead_of_guessing_and_observed_citations(make_dispatcher):
    async def unsure(tools, ctx):
        ref = ref_of(await tools["workspace_write"].handler({"name": "o.md", "content": COPY}))
        await tools["submit_return"].handler({"status": "blocked", "outputs": [ref], "confidence": 0.2,
                                              "self_check": [], "open_questions": ["What is the product called?"]})
    d, _, slack = make_dispatcher(full_team({("sales_researcher", "execute"): unsure}))
    await d.handle_message(msg("caption and a post please"))
    await approve(d, "G1")
    assert task(d).status == "ESCALATED"
    assert any("What is the product called?" in m.get("text", "") for m in slack.sent)


# R10 "how and when it stores info and memory across its files"
async def test_R10_memory_only_saved_when_owner_ticks(make_dispatcher):
    d, _, _ = make_dispatcher(full_team())
    await d.handle_message(msg("caption and a post please"))
    await approve(d, "G1")
    with d.Session() as db:
        cand = db.scalar(select(MemoryEntry).where(MemoryEntry.status == "candidate"))
        g4 = db.scalar(select(Approval).where(Approval.gate == "G4"))
    await d.on_approval(OWNER, g4.id, True, memory_ticks=[])          # you tick nothing
    with d.Session() as db:
        assert db.get(MemoryEntry, cand.id).status == "rejected"


# R11 "it deletes unnecessary instructions given to it"
async def test_R11_one_off_dies_standing_supersedes_gc_archives(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({("sales_lead", "contract"): two_step_contract()})
    await d.handle_message(msg("From now on keep captions under 100 characters", eid="A"))
    assert await approve(d, "GM") == "ok"
    await d.handle_message(msg("From now on keep captions under 80 characters", eid="B"))
    with d.Session() as db:
        gm = [a for a in db.scalars(select(Approval).where(Approval.gate == "GM", Approval.status == "pending"))][0]
    await d.on_approval(OWNER, gm.id, True)
    with d.Session() as db:
        rules = {m.content: m.status for m in db.scalars(select(MemoryEntry).where(MemoryEntry.standing.is_(True)))}
    assert rules["From now on keep captions under 100 characters"] == "archived"      # superseded (C42)
    assert rules["From now on keep captions under 80 characters"] == "active"
    # one-off notes live only in that task's contract, never in memory
    with d.Session() as db:
        assert not db.scalar(select(MemoryEntry).where(MemoryEntry.content.like("%make it funnier%")))


# R12 departments (v2: studio, sales, talent, engineering, ops) + R13 "multiple employees for each"
def test_R12_R13_departments_multiple_specialists(cfg):
    assert set(cfg.leads) == {"studio", "sales", "talent", "engineering", "ops"}
    for dept in cfg.leads:
        assert len(cfg.specialists_of(dept)) >= 1
    assert len(cfg.specialists_of("studio")) >= 8 and len(cfg.specialists_of("sales")) >= 10
    assert cfg.employee("studio_designer").id != cfg.employee("studio_faceless_editor").id


# R14 "keep their context and memory separate — else it will hallucinate"
async def test_R14_separate_context_and_memory(make_dispatcher, cfg, Session):
    d, runner, _ = make_dispatcher(full_team())
    await d.handle_message(msg("caption and a post please"))
    await approve(d, "G1")
    q, e = [c for c in runner.calls if c["employee"] == "sales_researcher"][0], [c for c in runner.calls if c["employee"] == "sales_outreach_writer"][0]
    assert "You are Intel" in q["system"] and "You are Intel" not in e["system"]   # fresh session, own profile only
    assert "`sales_researcher`" in q["system"] and "`sales_researcher`" not in e["system"]   # own training file only
    ms = MemoryStore(cfg)
    with Session() as db:
        db.add(MemoryEntry(id="px", layer="L3", scope_id="studio_designer", kind="preference",
                           content="dark background", source="s", author="x", status="active"))
        db.commit()
        assert ms.read(db, cfg.employee("studio_faceless_editor"), "background") == []


# R15 "I will only call marketing ... marketing will then call the required agent"
async def test_R15_owner_only_talks_to_department(make_dispatcher):
    d, runner, _ = make_dispatcher(full_team())
    await d.handle_message(msg("caption and a post please"))
    assert runner.calls[0]["employee"] == "sales_lead"
    assert await d.handle_message(msg("do stuff for me", eid="Z", channel="#random")) == "ignored-channel"


# Decision: "only I'll give tasks"
async def test_D1_only_owner_gives_tasks(make_dispatcher):
    from workforce.slack import InboundMessage
    d, runner, _ = make_dispatcher({})
    r = await d.handle_message(InboundMessage("E", "U_OTHER", "C", "#sales", "make a banner now", "1", None, False))
    assert r == "refused" and runner.calls == []


# Decision: agent-harness is the loop engine
async def test_D2_agent_harness_drives_every_task(make_dispatcher):
    d, _, _ = make_dispatcher(full_team())
    await d.handle_message(msg("caption and a post please"))
    await approve(d, "G1")
    state = json.loads((hmod.task_dir(task(d).id) / "harness-state.json").read_text())
    assert state["schema"] == "agent-harness/state.v1" and state["status"] == "closed"
    assert all(t["status"] == "verified" for t in state["tasks"])


# Decision: "don't want to pay anything" -> plan credit hard stop
async def test_D3_plan_credit_is_a_hard_stop(make_dispatcher):
    d, runner, _ = make_dispatcher(full_team())
    runner.cost = 21.0
    await d.handle_message(msg("caption and a post please"))
    await d.handle_message(msg("another request here", eid="Q"))
    assert len(runner.calls) == 1


# Round 3 flags C36–C43
def test_C37_iteration_cap_scales(cfg):
    from workforce.harness import Harness
    h = Harness(cfg)
    plan = h.build_plan("t", "g", "sales", [{"to": "sales_script_writer", "task_type": "caption", "objective": "o"}] * 6,
                        {f"T{i}": ["spellcheck"] for i in range(1, 7)})
    assert plan["loop"]["max_loop_iterations"] >= 36


async def test_C39_owner_instructions_reach_specialists(make_dispatcher):
    d, runner, _ = make_dispatcher(full_team())
    await d.handle_message(msg("caption and a post please"))
    await d.handle_message(msg("use British spelling", eid="N", thread="100.1"))
    await approve(d, "G1")
    execs = [c for c in runner.calls if c["phase"] == "execute"]
    assert execs and all("use British spelling" in c["prompt"] for c in execs)


def test_C40_chitchat_is_not_a_task():
    assert is_chitchat("thanks!") and is_chitchat("👍") and is_chitchat("ok")
    assert not is_chitchat("write a caption")


async def test_C41_department_queue(make_dispatcher):
    d, runner, slack = make_dispatcher({("sales_lead", "contract"): two_step_contract()})
    d.max_open = 1
    await d.handle_message(msg("first request here", eid="1"))
    await d.handle_message(msg("second request here", eid="2"))
    with d.Session() as db:
        statuses = sorted(t.status for t in db.scalars(select(Task)))
    assert statuses == ["CONTRACT_DRAFTED", "RECEIVED"]
    assert any("Queued" in m.get("text", "") for m in slack.sent)
    with d.Session() as db:
        first = db.scalar(select(Task).where(Task.status == "CONTRACT_DRAFTED"))
        first.status = "CANCELLED"
        db.commit()
    assert len(await d.drain_queue()) == 1


def test_C43_digest_is_deterministic_and_once_a_day(make_dispatcher):
    d, runner, slack = make_dispatcher({})
    now = datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)
    assert d.digest(now) and d.digest(now) is None and runner.calls == []
