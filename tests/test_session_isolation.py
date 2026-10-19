"""Org v3 §3c: Claude Code's native session talk stays off in every employee session.

SDKRunner is driven with a stand-in ClaudeSDKClient that records the options it gets; no Claude call is made.
"""
import claude_agent_sdk
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from workforce.agents import ISOLATION_ENV, NATIVE_AGENT_TOOLS, SDKRunner, ToolSpec, ok


class RecordingClient:
    seen = []

    def __init__(self, options):
        self.options = options
        RecordingClient.seen.append(options)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt):
        pass

    async def receive_response(self):
        return
        yield  # pragma: no cover — makes this an async generator


async def _run(monkeypatch, builtins=None):
    RecordingClient.seen.clear()
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", RecordingClient)

    async def handler(_args):
        return ok("done")

    async def gate(_name, _input):
        return True, ""

    await SDKRunner().run(employee_id="sales_researcher", model="claude-haiku-5-5", phase="execute", system="s",
                          prompt="p", tools=[ToolSpec("submit_return", "d", {"type": "object"}, handler)],
                          builtins=builtins or {}, gate=gate, max_turns=3, budget_usd=0.1)
    return RecordingClient.seen[-1]


async def test_native_agent_tools_are_disallowed(monkeypatch):
    opts = await _run(monkeypatch)
    for name in ("SendMessage", "ListAgents", "Agent", "Task"):
        assert name in opts.disallowed_tools
    assert opts.tools == []                     # no built-in tools at all
    assert opts.setting_sources == []           # no user/project settings that could switch them back on
    assert not opts.agents                      # no subagent roster


async def test_messaging_socket_and_agent_teams_blanked_even_if_server_env_sets_them(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", "/tmp/peer.sock")
    monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
    opts = await _run(monkeypatch)
    for key in ISOLATION_ENV:
        assert opts.env[key] == ""              # options.env overrides the inherited server environment


async def test_permission_callback_refuses_native_tools_even_when_web_is_allowed(monkeypatch):
    opts = await _run(monkeypatch, builtins={"WebSearch": "web.search"})
    for name in NATIVE_AGENT_TOOLS:
        assert isinstance(await opts.can_use_tool(name, {"to": "show_sherlock_writer"}, None), PermissionResultDeny)
    assert isinstance(await opts.can_use_tool("WebSearch", {"query": "x"}, None), PermissionResultAllow)


async def test_effort_fallback_passed_and_advisor_disabled_by_default(monkeypatch):
    RecordingClient.seen.clear()
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", RecordingClient)

    async def gate(_name, _input):
        return True, ""

    await SDKRunner().run(employee_id="eng_backend", model="claude-sonnet-5-5", phase="execute", system="s", prompt="p",
                          tools=[], builtins={}, gate=gate, max_turns=3, budget_usd=0.1,
                          effort="medium", fallback_model="claude-opus-5-5", advisor=None)
    opts = RecordingClient.seen[-1]
    assert (opts.effort, opts.fallback_model, opts.settings) == ("medium", "claude-opus-5-5", None)
    assert opts.env["CLAUDE_CODE_DISABLE_ADVISOR_TOOL"] == "1"
