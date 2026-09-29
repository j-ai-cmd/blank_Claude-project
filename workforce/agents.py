"""Agent runners. One fresh session per employee per task step.

SDKRunner runs the Claude Agent SDK on the owner's Claude plan (CLAUDE_CODE_OAUTH_TOKEN), with every
built-in tool disabled except explicitly mapped ones that are gated by the Dispatcher's policy.
FakeRunner drives the same tool handlers from a script, for tests and dry runs.
"""
from __future__ import annotations

import asyncio
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
    turns: int = 0
    errors: list[str] = field(default_factory=list)


def ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def err(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


class AgentRunner(Protocol):
    async def run(self, *, employee_id: str, model: str, phase: str, system: str, prompt: str,
                  tools: list[ToolSpec], builtins: dict[str, str], gate: Gate,
                  max_turns: int, budget_usd: float) -> RunResult: ...


def ensure_plan_billing() -> None:
    """Plan billing: an API key in the environment would silently switch to pay-as-you-go."""
    if os.environ.get("WORKFORCE_BILLING", "plan") == "plan" and os.environ.pop("ANTHROPIC_API_KEY", None):
        print("[workforce] ANTHROPIC_API_KEY removed from environment: billing mode is 'plan' (Agent SDK credit).")


class SDKRunner:
    def __init__(self):
        ensure_plan_billing()

    async def run(self, *, employee_id, model, phase, system, prompt, tools, builtins, gate, max_turns, budget_usd):
        from claude_agent_sdk import (ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow,
                                      PermissionResultDeny, ResultMessage, create_sdk_mcp_server, tool)

        sdk_tools = []
        for spec in tools:
            sdk_tools.append(tool(spec.name, spec.description, spec.schema)(spec.handler))
        server = create_sdk_mcp_server(name="wf", version="1.0.0", tools=sdk_tools)

        async def can_use_tool(tool_name: str, tool_input: dict, _ctx: Any):
            if tool_name in builtins:
                allowed, msg = await gate(tool_name, tool_input)
                return PermissionResultAllow() if allowed else PermissionResultDeny(message=msg)
            return PermissionResultDeny(message=f"{tool_name} is not available to {employee_id}")

        workdir = tempfile.mkdtemp(prefix=f"wf-{employee_id}-")  # empty; agents have no file tools anyway
        options = ClaudeAgentOptions(
            tools=list(builtins),                                  # [] = every built-in tool off
            allowed_tools=[f"mcp__wf__{t.name}" for t in tools],   # Dispatcher tools (they self-check policy)
            mcp_servers={"wf": server},
            strict_mcp_config=True,
            setting_sources=[],                                    # ignore user/project settings, CLAUDE.md, skills dirs
            system_prompt=system,
            model=model,
            max_turns=max_turns,
            max_budget_usd=max(0.01, budget_usd),
            permission_mode="default",
            can_use_tool=can_use_tool,
            cwd=workdir,
        )
        res = RunResult()
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, ResultMessage):
                    res.cost_usd = float(msg.total_cost_usd or 0.0)
                    res.is_error = bool(msg.is_error)
                    res.text = msg.result or ""
                    res.turns = msg.num_turns
                    res.errors = list(msg.errors or [])
        return res


Script = Callable[[dict[str, ToolSpec], dict], Awaitable[None]]


class FakeRunner:
    """scripts[(employee_id, phase)] = async fn(tools_by_name, ctx) that calls tool handlers."""

    def __init__(self, scripts: dict[tuple[str, str], Script] | None = None, cost_per_run: float = 0.01):
        self.scripts = scripts or {}
        self.cost = cost_per_run
        self.calls: list[dict] = []
        self.script_errors: list[str] = []   # tests assert this stays empty

    async def run(self, *, employee_id, model, phase, system, prompt, tools, builtins, gate, max_turns, budget_usd):
        self.calls.append({"employee": employee_id, "phase": phase, "prompt": prompt, "system": system,
                           "tools": [t.name for t in tools], "builtins": dict(builtins)})
        fn = self.scripts.get((employee_id, phase)) or self.scripts.get(("*", phase))
        if fn is None:
            return RunResult(cost_usd=self.cost, is_error=True, text=f"no script for {employee_id}/{phase}")
        try:
            await fn({t.name: t for t in tools}, {"prompt": prompt, "gate": gate, "system": system})
        except Exception as e:  # noqa: BLE001
            import traceback
            self.script_errors.append(f"{employee_id}/{phase}: {e!r}\n{traceback.format_exc()}")
            raise
        return RunResult(cost_usd=self.cost, text="ok", turns=1)


def run_sync(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)  # pragma: no cover
