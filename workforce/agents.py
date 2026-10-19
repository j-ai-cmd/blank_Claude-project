"""Agent runners. One fresh session per employee per task step.

SDKRunner runs the Claude Agent SDK on the owner's Claude plan (CLAUDE_CODE_OAUTH_TOKEN), with every
built-in tool disabled except explicitly mapped ones that are gated by the Dispatcher's policy.
FakeRunner drives the same tool handlers from a script, for tests and dry runs.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

Handler = Callable[[dict], Awaitable[dict]]
Gate = Callable[[str, dict], Awaitable[tuple[bool, str]]]


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict
    handler: Handler


@dataclass
class RunResult:
    cost_usd: float = 0.0
    is_error: bool = False
    text: str = ""
    errors: list[str] = field(default_factory=list)
    session_id: str | None = None   # set when the run can be resumed (lead sessions, ORG-V3 step 8)
    usage: dict = field(default_factory=dict)   # token counts from the CLI (input, cache read/write, output)


def ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def err(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


class AgentRunner(Protocol):
    async def run(self, *, employee_id: str, model: str, phase: str, system: str, prompt: str,
                  tools: list[ToolSpec], builtins: dict[str, str], gate: Gate,
                  max_turns: int, budget_usd: float, effort: str | None = None, fallback_model: str | None = None,
                  advisor: str | None = None, session: dict | None = None) -> RunResult: ...


# Claude Code's own multi-agent features would let one employee's session reach another past Policy.check:
# cross-session messaging over a local socket, subagents, agent teams. All workforce sessions share one
# server, so these stay off in every session (ORG-V3 §3c). Peer messages go through Dispatcher tools only.
NATIVE_AGENT_TOOLS = ["SendMessage", "ListAgents", "Agent", "Task"]
ISOLATION_ENV = {
    "CLAUDE_CODE_MESSAGING_SOCKET": "",            # no inbox: other sessions can't deliver to this one
    "CLAUDE_CODE_MESSAGING_TOKEN": "",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "",    # no teammates
}


def ensure_plan_billing() -> None:
    """Plan billing: an API key in the environment would silently switch to pay-as-you-go."""
    if os.environ.get("WORKFORCE_BILLING", "plan") == "plan" and os.environ.pop("ANTHROPIC_API_KEY", None):
        print("[workforce] ANTHROPIC_API_KEY removed from environment: billing mode is 'plan' (Agent SDK credit).")


class SDKRunner:
    def __init__(self):
        ensure_plan_billing()

    async def run(self, *, employee_id, model, phase, system, prompt, tools, builtins, gate, max_turns, budget_usd,
                  effort=None, fallback_model=None, advisor=None, session=None):
        from claude_agent_sdk import (ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, PermissionResultAllow,
                                      PermissionResultDeny, ResultMessage, create_sdk_mcp_server, tool)

        sdk_tools = []
        for spec in tools:
            sdk_tools.append(tool(spec.name, spec.description, spec.schema)(spec.handler))
        server = create_sdk_mcp_server(name="wf", version="1.0.0", tools=sdk_tools)

        gated: set[str] = set()   # built-in calls the PreToolUse hook already passed through the gate

        def _key(tool_name: str, tool_input: dict) -> str:
            return tool_name + json.dumps(tool_input, sort_keys=True, default=str)

        async def pre_tool_use(input_data: dict, _tool_use_id: str | None, _ctx: Any) -> dict:
            """Runs before EVERY tool call. can_use_tool alone is not enough: the CLI skips the permission
            callback for calls it pre-approves (e.g. WebFetch to Anthropic's own docs), which bypassed the gate."""
            name, args = input_data.get("tool_name", ""), input_data.get("tool_input") or {}
            if name.startswith("mcp__wf__"):
                return {}                                     # Dispatcher tools check policy themselves (_guard)
            if name in builtins:
                allowed, msg = await gate(name, args)
                if allowed:
                    gated.add(_key(name, args))
                    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
                reason = msg
            elif name in NATIVE_AGENT_TOOLS:
                reason = f"{name} is disabled: employees talk only through the Dispatcher"
            else:
                reason = f"{name} is not available to {employee_id}"
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}

        async def can_use_tool(tool_name: str, tool_input: dict, _ctx: Any):
            if tool_name in NATIVE_AGENT_TOOLS:
                return PermissionResultDeny(message=f"{tool_name} is disabled: employees talk only through the Dispatcher")
            if tool_name in builtins:
                if _key(tool_name, tool_input) in gated:          # already checked + audited by the hook
                    gated.discard(_key(tool_name, tool_input))
                    return PermissionResultAllow()
                allowed, msg = await gate(tool_name, tool_input)
                return PermissionResultAllow() if allowed else PermissionResultDeny(message=msg)
            return PermissionResultDeny(message=f"{tool_name} is not available to {employee_id}")

        if session:   # a lead's task session: kept on disk (inside the task workspace) so the next phase can resume it
            from pathlib import Path
            base = Path(session["dir"])
            workdir, confdir = str(base / "work"), str(base / "cfg")
            os.makedirs(workdir, exist_ok=True)
            os.makedirs(confdir, exist_ok=True)
        else:
            workdir = tempfile.mkdtemp(prefix=f"wf-{employee_id}-")  # empty; agents have no file tools anyway
            confdir = tempfile.mkdtemp(prefix=f"wf-cfg-{employee_id}-")  # C36: no user skills/CLAUDE.md/memory/transcripts
        options = ClaudeAgentOptions(
            tools=list(builtins),                                  # [] = every built-in tool off
            allowed_tools=[f"mcp__wf__{t.name}" for t in tools],   # Dispatcher tools (they self-check policy)
            disallowed_tools=list(NATIVE_AGENT_TOOLS),             # no native cross-session talk or subagents
            mcp_servers={"wf": server},
            strict_mcp_config=True,
            setting_sources=[],                                    # ignore user/project settings, CLAUDE.md, skills dirs
            system_prompt=system,
            model=model,
            effort=effort,
            fallback_model=fallback_model if fallback_model != model else None,
            # /advisor in Claude Code: `--advisor <model>` turns on the server-side advisor tool, so the executor can
            # consult a stronger model at key moments. Off unless config/org.yaml models.advisor.enabled.
            extra_args={"advisor": advisor} if advisor else {},
            max_turns=max_turns,
            resume=(session or {}).get("resume"),
            max_budget_usd=max(0.01, budget_usd),
            permission_mode="default",
            can_use_tool=can_use_tool,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])]},
            cwd=workdir,
            env={"CLAUDE_CONFIG_DIR": confdir, **ISOLATION_ENV,
                 **({} if advisor else {"CLAUDE_CODE_DISABLE_ADVISOR_TOOL": "1"})},
        )
        res = RunResult()
        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                async for msg in client.receive_response():
                    if isinstance(msg, ResultMessage):
                        res.cost_usd = float(msg.total_cost_usd or 0.0)
                        res.is_error = bool(msg.is_error)
                        res.text = msg.result or ""
                        res.errors = list(msg.errors or [])
                        res.session_id = getattr(msg, "session_id", None) if session else None
                        res.usage = dict(msg.usage or {})
                        res.usage["models"] = sorted((getattr(msg, "model_usage", None) or {}).keys())   # shows advisor calls
        finally:
            if not session:   # session dirs are removed by the Dispatcher when the task is delivered or cancelled
                import shutil
                shutil.rmtree(workdir, ignore_errors=True)
                shutil.rmtree(confdir, ignore_errors=True)
        return res


Script = Callable[[dict[str, ToolSpec], dict], Awaitable[None]]


class FakeRunner:
    """scripts[(employee_id, phase)] = async fn(tools_by_name, ctx) that calls tool handlers."""

    def __init__(self, scripts: dict[tuple[str, str], Script] | None = None, cost_per_run: float = 0.01):
        self.scripts = scripts or {}
        self.cost = cost_per_run
        self.calls: list[dict] = []
        self.script_errors: list[str] = []   # tests assert this stays empty

    async def run(self, *, employee_id, model, phase, system, prompt, tools, builtins, gate, max_turns, budget_usd,
                  effort=None, fallback_model=None, advisor=None, session=None):
        self.calls.append({"employee": employee_id, "phase": phase, "prompt": prompt, "system": system,
                           "tools": [t.name for t in tools], "builtins": dict(builtins), "model": model,
                           "effort": effort, "fallback_model": fallback_model, "advisor": advisor,
                           "session": dict(session) if session else None})
        fn = self.scripts.get((employee_id, phase)) or self.scripts.get(("*", phase))
        if fn is None:
            return RunResult(cost_usd=self.cost, is_error=True, text=f"no script for {employee_id}/{phase}")
        try:
            await fn({t.name: t for t in tools}, {"prompt": prompt, "gate": gate, "system": system})
        except Exception as e:  # noqa: BLE001
            import traceback
            self.script_errors.append(f"{employee_id}/{phase}: {e!r}\n{traceback.format_exc()}")
            raise
        return RunResult(cost_usd=self.cost, text="ok",
                         session_id=f"fake-{employee_id}-{len(self.calls)}" if session else None)

