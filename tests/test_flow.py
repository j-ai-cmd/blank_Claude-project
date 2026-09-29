"""End-to-end: Slack message -> contract -> plan -> agent-harness (real controller + real checks) ->
Verifier -> delivery -> G4 -> memory. Agents are scripted with FakeRunner (no model calls)."""
from sqlalchemy import select

from workforce.db import Approval, AuditEvent, MemoryEntry, Task
from workforce.slack import InboundMessage

OWNER = "U_OWNER"
GOOD_COPY = "Our new planner helps small teams finish work sooner."
SLOP_COPY = "Let's delve into this tapestry. It's a game-changer that will elevate your seamless workflow."


def msg(text, user=OWNER, channel="#marketing", thread=None, eid="E1"):
    return InboundMessage(event_id=eid, user=user, channel="C_MKT", channel_name=channel, text=text,
                          ts="100.1", thread_ts=thread, is_dm=False)


def contract(size="S", n=1):
    async def fn(tools, ctx):
        r = await tools["submit_contract"].handler({
            "objective": "Write a launch caption", "size": size,
            "deliverables": [{"id": "D1", "description": "caption", "format": "md",
                              "assignee": "mkt_copywriter", "task_type": "general_copy"}],
            "acceptance_criteria": [{"id": str(i), "text": f"criterion {i}", "check": "automatic"} for i in range(1, n + 1)]})
        assert not r.get("is_error"), r
    return fn


def plan(n=1):
    async def fn(tools, ctx):
        r = await tools["submit_plan"].handler({"handoffs": [{
            "deliverable": "D1", "to": "mkt_copywriter", "task_type": "general_copy", "objective": "caption",
            "criteria": [str(i) for i in range(1, n + 1)], "inputs": [], "context_summary": "launch"}]})
        assert not r.get("is_error"), r
    return fn


def writer(texts, n=1):
    calls = {"i": 0}

    async def fn(tools, ctx):
        text = texts[min(calls["i"], len(texts) - 1)]
        calls["i"] += 1
        saved = await tools["workspace_write"].handler({"name": "caption.md", "content": text})
        ref = saved["content"][0]["text"].removeprefix("saved ")
        r = await tools["submit_return"].handler({
            "status": "done", "outputs": [ref], "confidence": 0.9,
            "self_check": [{"criterion_id": str(i), "result": "met", "evidence": "checked"} for i in range(1, n + 1)],
            "memory_candidates": [{"content": "Owner likes short captions"}]})
        assert not r.get("is_error"), r
    return fn


async def delivery(tools, ctx):
    await tools["submit_delivery"].handler({"note": "Caption is ready."})


def verdict(results):
    calls = {"i": 0}

    async def fn(tools, ctx):
        res = results[min(calls["i"], len(results) - 1)]
        calls["i"] += 1
        await tools["submit_verdict"].handler({"grades": [{"criterion_id": "1", "result": res, "evidence": "e"}]})
    return fn


def _task(d):
    with d.Session() as db:
        return db.scalars(select(Task)).first()


async def test_small_task_end_to_end(make_dispatcher):
    d, runner, slack = make_dispatcher({
        ("mkt_lead", "contract"): contract("S"), ("mkt_lead", "plan"): plan(),
        ("mkt_copywriter", "execute"): writer([GOOD_COPY]), ("mkt_lead", "deliver"): delivery})
    await d.handle_message(msg("write a launch caption"))
    t = _task(d)
    assert t.status == "DELIVERED", t.status
    assert t.g1_approval_id.startswith("auto-S")
    assert t.verification_id.startswith("auto-checks")          # S internal task: machine checks only
    phases = [c["phase"] for c in runner.calls]
    assert phases == ["contract", "plan", "execute", "deliver"]  # no LLM verifier for S
    assert runner.calls[2]["builtins"] == {"WebSearch": "web.search", "WebFetch": "web.fetch"}  # gated by policy
    assert "humanizer" in runner.calls[2]["system"]              # routed skill loaded
    with d.Session() as db:
        g4 = db.scalar(select(Approval).where(Approval.gate == "G4"))
        cand = db.scalar(select(MemoryEntry))
    assert await d.on_approval("U_STRANGER", g4.id, True) == "not-an-approver"
    await d.on_approval(OWNER, g4.id, True, memory_ticks=[cand.id])
    t = _task(d)
    assert t.status == "CLOSED"
    with d.Session() as db:
        assert db.get(MemoryEntry, cand.id).status == "active"


async def test_medium_task_needs_g1_and_verifier_revision(make_dispatcher):
    d, runner, _ = make_dispatcher({
        ("mkt_lead", "contract"): contract("M"), ("mkt_lead", "plan"): plan(),
        ("mkt_copywriter", "execute"): writer([GOOD_COPY]), ("mkt_lead", "deliver"): delivery,
        ("verifier", "verify"): verdict(["FAIL", "PASS"])})
    await d.handle_message(msg("write a launch caption"))
    t = _task(d)
    assert t.status == "CONTRACT_DRAFTED"                        # waits for owner at G1
    with d.Session() as db:
        g1 = db.scalar(select(Approval).where(Approval.gate == "G1"))
    await d.on_approval(OWNER, g1.id, True)
    t = _task(d)
    assert t.status == "DELIVERED", t.status
    assert t.revisions == 1                                     # one Verifier FAIL -> revision -> PASS
    assert [c["phase"] for c in runner.calls].count("verify") == 2
    assert t.verification_id.startswith("ver_")


async def test_failing_checks_retry_then_escalate(make_dispatcher):
    d, runner, slack = make_dispatcher({
        ("mkt_lead", "contract"): contract("S"), ("mkt_lead", "plan"): plan(),
        ("mkt_copywriter", "execute"): writer([SLOP_COPY])})
    await d.handle_message(msg("write a launch caption"))
    t = _task(d)
    assert t.status == "ESCALATED"
    assert [c["phase"] for c in runner.calls].count("execute") == 3   # max_attempts_per_task
    # failure notes were fed back into the retry prompt
    assert "no_ai_tells" in runner.calls[-1]["prompt"]


async def test_retry_succeeds_with_changed_approach(make_dispatcher):
    d, runner, _ = make_dispatcher({
        ("mkt_lead", "contract"): contract("S"), ("mkt_lead", "plan"): plan(),
        ("mkt_copywriter", "execute"): writer([SLOP_COPY, GOOD_COPY]), ("mkt_lead", "deliver"): delivery})
    await d.handle_message(msg("write a launch caption"))
    assert _task(d).status == "DELIVERED"


async def test_non_owner_refused_and_duplicate_ignored(make_dispatcher):
    d, runner, slack = make_dispatcher({})
    assert await d.handle_message(msg("do stuff", user="U_GUEST")) == "refused"
    assert runner.calls == []
    assert await d.handle_message(msg("do stuff", user="U_GUEST")) == "duplicate"


async def test_invalid_plan_route_rejected(make_dispatcher):
    async def bad_plan(tools, ctx):
        r = await tools["submit_plan"].handler({"handoffs": [{
            "deliverable": "D1", "to": "mkt_copywriter", "task_type": "banner_or_ad", "objective": "x", "criteria": ["1"]}]})
        assert r.get("is_error") and "is not a route" in r["content"][0]["text"] and "was approved for" in r["content"][0]["text"]
    d, runner, _ = make_dispatcher({("mkt_lead", "contract"): contract("S"), ("mkt_lead", "plan"): bad_plan})
    await d.handle_message(msg("write a launch caption"))
    assert _task(d).status == "CANCELLED"


async def test_owner_steering_creates_new_contract_version(make_dispatcher):
    d, runner, _ = make_dispatcher({("mkt_lead", "contract"): contract("M")})
    await d.handle_message(msg("write a launch caption"))
    await d.handle_message(msg("make it funnier", thread="100.1", eid="E2"))
    t = _task(d)
    assert t.contract_version == 2 and t.contract["_owner_notes"] == ["make it funnier"]
    with d.Session() as db:
        statuses = sorted(a.status for a in db.scalars(select(Approval).where(Approval.gate == "G1")))
    assert statuses == ["expired", "pending"]


async def test_monthly_credit_pauses_everything(make_dispatcher):
    d, runner, _ = make_dispatcher({("mkt_lead", "contract"): contract("M")})
    runner.cost = 25.0  # one run burns more than the $20 Pro credit
    await d.handle_message(msg("write a launch caption"))
    with d.Session() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.kind == "pause")) is not None
    assert "paused" in d.command(OWNER, "status") or "Plan credit used" in d.command(OWNER, "status")
    await d.handle_message(msg("another", eid="E9"))
    assert [c["phase"] for c in runner.calls] == ["contract"]      # second task never reached the model


async def test_r2_actions_become_hash_bound_g3(make_dispatcher):
    async def social(tools, ctx):
        saved = await tools["workspace_write"].handler({"name": "post.md", "content": GOOD_COPY})
        ref = saved["content"][0]["text"].removeprefix("saved ")
        r = await tools["submit_return"].handler({
            "status": "done", "outputs": [ref], "confidence": 0.9,
            "self_check": [{"criterion_id": "1", "result": "met", "evidence": "ok"}],
            "pending_actions": [{"action": "social.publish", "params": {"text": GOOD_COPY}, "preview": GOOD_COPY}]})
        assert not r.get("is_error"), r

    async def plan_social(tools, ctx):
        r = await tools["submit_plan"].handler({"handoffs": [{"deliverable": "D1", "to": "mkt_social_manager", "task_type": "linkedin_post",
                                                              "objective": "post", "criteria": ["1"], "platform": "linkedin"}]})
        assert not r.get("is_error"), r

    async def contract_social(tools, ctx):
        r = await tools["submit_contract"].handler({
            "objective": "Post launch", "size": "M", "planned_actions_tiers": ["R2"],
            "deliverables": [{"id": "D1", "description": "post", "format": "md",
                              "assignee": "mkt_social_manager", "task_type": "linkedin_post"}],
            "acceptance_criteria": [{"id": "1", "text": "post ready", "check": "automatic"}]})
        assert not r.get("is_error"), r
    d, runner, slack = make_dispatcher({
        ("mkt_lead", "contract"): contract_social, ("mkt_lead", "plan"): plan_social,
        ("mkt_social_manager", "execute"): social, ("mkt_lead", "deliver"): delivery,
        ("verifier", "verify"): verdict(["PASS"])})
    await d.handle_message(msg("post our launch on linkedin"))
    with d.Session() as db:
        g1 = db.scalar(select(Approval).where(Approval.gate == "G1"))
    await d.on_approval(OWNER, g1.id, True)
    with d.Session() as db:
        g4 = db.scalar(select(Approval).where(Approval.gate == "G4"))
    await d.on_approval(OWNER, g4.id, True)
    with d.Session() as db:
        g3 = db.scalar(select(Approval).where(Approval.gate == "G3"))
    assert g3.action == "social.publish" and g3.tier == "R2"
    assert await d.on_approval(OWNER, g3.id, True, button_hash="tampered") == "hash-mismatch"
    await d.on_approval(OWNER, g3.id, True, button_hash=g3.action_hash)
    assert any("no connector is configured" in s.get("text", "") for s in slack.sent)   # honest: nothing sent
