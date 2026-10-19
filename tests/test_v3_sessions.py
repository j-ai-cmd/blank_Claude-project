"""Org v3 step 8: a lead's contract -> plan -> deliver run as turns of one resumed session, only while warm."""
import json

import claude_agent_sdk

from tests.test_flow import GOOD_COPY, _task, contract, delivery, msg, plan, writer
from tests.test_session_isolation import RecordingClient
from workforce import dispatcher as dmod
from workforce.agents import SDKRunner
from workforce.harness import task_dir


def _flow(make_dispatcher):
    return make_dispatcher({
        ("sales_lead", "contract"): contract("S"), ("sales_lead", "plan"): plan(),
        ("sales_script_writer", "execute"): writer([GOOD_COPY]), ("sales_lead", "deliver"): delivery})


def _lead_calls(runner):
    return [c for c in runner.calls if c["employee"] == "sales_lead"]


async def test_lead_phases_resume_one_session_with_a_stable_prefix(make_dispatcher):
    d, runner, _ = _flow(make_dispatcher)
    await d.handle_message(msg("write a launch caption"))
    t = _task(d)
    assert t.status == "DELIVERED"
    c, p, dl = _lead_calls(runner)
    assert c["session"]["resume"] is None                                    # first turn starts the session
    assert p["session"]["resume"] == "fake-sales_lead-1"                     # plan resumes the contract turn
    assert dl["session"]["resume"] == f"fake-sales_lead-{runner.calls.index(p) + 1}"   # deliver resumes the latest turn
    assert c["system"] == p["system"] == dl["system"]                        # same cached prefix every turn
    assert c["tools"] == p["tools"] == dl["tools"] == ["submit_contract", "submit_plan", "submit_delivery"]
    assert c["effort"] == p["effort"] == dl["effort"] == "low"
    assert "# Phase" not in c["system"] and c["prompt"].startswith("# Phase")
    assert not (task_dir(t.id) / "sessions").exists()                        # removed once delivered (I8)


async def test_cold_session_is_not_resumed(make_dispatcher, monkeypatch):
    d, runner, _ = _flow(make_dispatcher)
    real = d._lead_session

    def aged(emp, task_id, model, system):          # pretend the last lead turn was an hour ago
        meta = task_dir(task_id) / "sessions" / emp.id / "meta.json"
        if meta.exists():
            m = json.loads(meta.read_text())
            m["last_at"] -= 3600
            meta.write_text(json.dumps(m))
        return real(emp, task_id, model, system)
    monkeypatch.setattr(d, "_lead_session", aged)
    await d.handle_message(msg("write a launch caption"))
    assert [c["session"]["resume"] for c in _lead_calls(runner)] == [None, None, None]


async def test_changed_system_prompt_starts_over(make_dispatcher, monkeypatch):
    d, runner, _ = _flow(make_dispatcher)
    calls = {"n": 0}
    real = dmod._digest

    def changing(text):                             # e.g. new memory arrived between phases
        calls["n"] += 1
        return real(text + str(calls["n"]))
    monkeypatch.setattr(dmod, "_digest", changing)
    await d.handle_message(msg("write a launch caption"))
    assert all(c["session"]["resume"] is None for c in _lead_calls(runner))


async def test_off_phase_tool_is_refused(make_dispatcher):
    async def wrong_tool_first(tools, ctx):
        r = await tools["submit_plan"].handler({"handoffs": []})
        assert r.get("is_error") and "contract phase" in r["content"][0]["text"]
        await contract("S")(tools, ctx)
    d, _, _ = make_dispatcher({("sales_lead", "contract"): wrong_tool_first, ("sales_lead", "plan"): plan(),
                               ("sales_script_writer", "execute"): writer([GOOD_COPY]), ("sales_lead", "deliver"): delivery})
    await d.handle_message(msg("write a launch caption"))
    assert _task(d).status == "DELIVERED"


async def test_sdk_runner_resumes_and_keeps_session_dirs(monkeypatch, tmp_path):
    RecordingClient.seen.clear()
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", RecordingClient)

    async def gate(_n, _i):
        return True, ""
    sess = {"dir": str(tmp_path / "sessions" / "sales_lead"), "resume": "abc-123"}
    await SDKRunner().run(employee_id="sales_lead", model="claude-sonnet-5-5", phase="plan", system="s", prompt="p",
                          tools=[], builtins={}, gate=gate, max_turns=3, budget_usd=0.1, session=sess)
    opts = RecordingClient.seen[-1]
    assert opts.resume == "abc-123" and opts.cwd.startswith(sess["dir"])
    assert (tmp_path / "sessions" / "sales_lead" / "cfg").is_dir()          # kept for the next phase
    await SDKRunner().run(employee_id="sales_researcher", model="claude-haiku-5-5", phase="execute", system="s",
                          prompt="p", tools=[], builtins={}, gate=gate, max_turns=3, budget_usd=0.1)
    assert RecordingClient.seen[-1].resume is None                           # specialists stay one-shot
