"""Org v3 step 9: peer_ask — a specialist asks a finished UPSTREAM step of the same task; the Dispatcher relays."""
import json

from sqlalchemy import select

from tests.test_flags import COPY, approve, delivery, msg, poster, task, two_step_contract, two_step_plan, writer
from workforce.db import AuditEvent, Task
from workforce.harness import plan_task_dir


async def test_writer_asks_researcher_and_dispatcher_relays_one_shot(make_dispatcher):
    seen = {}

    async def hook(tools, ctx):
        assert "peer_ask" in tools
        r = await tools["peer_ask"].handler({"to": "sales_researcher", "question": "Which source says they edit talks?"})
        seen["answer"] = r["content"][0]["text"]
        bad = await tools["peer_ask"].handler({"to": "sales_proposal_writer", "question": "hi"})
        seen["not_upstream"] = bad.get("is_error")
        await poster({})(tools, ctx)

    async def intel_answers(tools, ctx):
        assert set(tools) == {"workspace_read", "submit_answer"}           # read own work, answer; nothing else
        assert "<untrusted" in ctx["prompt"] and "Which source" in ctx["prompt"]
        await tools["submit_answer"].handler({"answer": "artifact T1-out.md, from the cited page"})

    d, runner, _ = make_dispatcher({
        ("sales_lead", "contract"): two_step_contract(), ("sales_lead", "plan"): two_step_plan,
        ("sales_researcher", "execute"): writer(COPY), ("sales_outreach_writer", "execute"): hook,
        ("sales_researcher", "peer_answer"): intel_answers, ("sales_lead", "deliver"): delivery})
    await d.handle_message(msg("research the client and pitch them"))
    await approve(d, "G1")
    assert task(d).status == "DELIVERED"
    assert "from the cited page" in seen["answer"] and "<untrusted" in seen["answer"]
    assert seen["not_upstream"]
    ans = next(c for c in runner.calls if c["phase"] == "peer_answer")
    assert ans["builtins"] == {}                                             # no web for the answering peer
    with d.Session() as db:
        ev = db.scalar(select(AuditEvent).where(AuditEvent.kind == "peer_ask"))
        assert ev.detail["pair"] == "T2->T1" and ev.actor == "sales_outreach_writer"


def _setup(d, cfg, asker_id, peer_id, tid="pa1"):
    with d.Session() as db:
        db.add(Task(id=tid, department="sales", requested_by="U_OWNER", original_request="x", contract_version=1,
                    status="IN_PROGRESS"))
        db.commit()
    packets = [{"to": peer_id, "task_type": "job_brief", "objective": "brief", "criteria": ["1"]},
               {"to": asker_id, "task_type": "cover_letter", "objective": "letter", "criteria": ["1"], "inputs_from": ["T1"]}]
    plan_task_dir(tid, "T1").mkdir(parents=True, exist_ok=True)
    (plan_task_dir(tid, "T1") / "return.json").write_text(json.dumps({"summary": "brief", "outputs": []}))
    return d._peer_ask_tool(cfg.employee(asker_id), tid, "T2", packets, {})


async def test_limits_pii_and_private_data_to_web_peer(make_dispatcher, cfg):
    async def answers(tools, ctx):
        await tools["submit_answer"].handler({"answer": "ok"})
    d, _, _ = make_dispatcher({("sales_researcher", "peer_answer"): answers})
    hook = _setup(d, cfg, "sales_outreach_writer", "sales_researcher")
    assert (await hook.handler({"to": "sales_researcher", "question": "Call +1 415 555 2671?"})).get("is_error")
    for _ in range(3):
        assert not (await hook.handler({"to": "sales_researcher", "question": "which page?"})).get("is_error")
    fourth = await hook.handler({"to": "sales_researcher", "question": "which page?"})
    assert fourth.get("is_error") and "3 times" in fourth["content"][0]["text"]
    letter = _setup(d, cfg, "sales_cover_letter_writer", "sales_researcher", tid="pa2")
    r = await letter.handler({"to": "sales_researcher", "question": "what does the JD stress?"})
    assert r.get("is_error") and "private data" in r["content"][0]["text"]


async def test_no_tool_when_nothing_upstream_finished(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({})
    packets = [{"to": "sales_outreach_writer", "task_type": "follow_up", "objective": "x", "criteria": ["1"]}]
    assert d._peer_ask_tool(cfg.employee("sales_outreach_writer"), "none", "T1", packets, {}) is None
