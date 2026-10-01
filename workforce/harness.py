"""Bridge to .claude/skills/agent-harness/scripts/loop_controller.py (config/harness.yaml).

The Dispatcher is the only caller. Agents never see or call the controller, never record verify,
never waive. Check commands come only from config/checks.yaml.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT, Config

CONTROLLER = ROOT / ".claude" / "skills" / "agent-harness" / "scripts" / "loop_controller.py"
WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", ROOT / "var" / "workspace"))


@dataclass
class Directive:
    action: str             # execute | verify | close | escalate | done
    task: str | None
    detail: dict
    code: int


class HarnessError(Exception):
    pass


def task_dir(task_id: str) -> Path:
    return WORKSPACE_ROOT / task_id


def plan_task_dir(task_id: str, pt_id: str) -> Path:
    return task_dir(task_id) / pt_id


def _cmd(template: str, task_id: str, pt_id: str, handoff: dict) -> str:
    """Fill placeholders; every substituted value is shell-quoted (plan files are a trust boundary)."""
    subs = {
        "{T}": shlex.quote(str(plan_task_dir(task_id, pt_id))),
        "{W}": shlex.quote(str(task_dir(task_id))),
        "{platform}": shlex.quote(str(handoff.get("platform", "") or "none")),
        "{url}": shlex.quote(str(handoff.get("url", "") or "")),
    }
    out = template
    for k, v in subs.items():
        out = out.replace(k, v)
    # {T}/x -> '<quoted dir>'/x is valid shell
    return out


class Harness:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.loop = cfg.harness["loop_defaults"]

    # ------------------------------------------------------------------ plan
    def build_plan(self, task_id: str, goal: str, dept: str, handoffs: list[dict],
                   route_checks: dict[str, list[str]]) -> dict:
        """One plan task per handoff. `route_checks[pt_id]` = resolved check ids for that handoff's route."""
        tasks = []
        for i, h in enumerate(handoffs, start=1):
            pt = f"T{i}"
            checks = []
            for cid in route_checks[pt]:
                spec = self.cfg.checks["checks"][cid]
                if spec.get("kind") != "executable":
                    continue
                checks.append({"cmd": _cmd(spec["cmd"], task_id, pt, h), "expect_exit": 0, "kind": "sample"})
            if not checks:
                raise HarnessError(f"{pt} has no executable checks — the harness would accept self-written evidence")
            tasks.append({
                "id": pt, "skill": h.get("task_type") or "craft", "skill_path": "",
                "objective": f"{h['to']}: {h['objective']}",
                "verification": checks,
                "done_when": "every verification check meets expect_exit",
                "max_attempts": int(self.loop["max_attempts_per_task"]), "status": "pending",
            })
        return {
            "schema": "agent-harness/plan.v1", "goal": goal, "domain": dept, "tasks": tasks,
            "loop": {"order": self.loop["order"],
                     "max_loop_iterations": max(int(self.loop["max_loop_iterations"]),
                                                2 * len(tasks) * int(self.loop["max_attempts_per_task"])),
                     "escalate_on": self.loop["escalate_on"]},
            "close": {"requires": "all tasks verified (or explicitly waived with a reason)"},
        }

    # ------------------------------------------------------------------ controller calls
    def _run(self, *args: str) -> tuple[dict, int]:
        env = dict(os.environ)
        env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
        env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}"
        p = subprocess.run([sys.executable, str(CONTROLLER), *args], capture_output=True, text=True,
                           cwd=str(ROOT), env=env, timeout=900)
        try:
            data = json.loads(p.stdout) if p.stdout.strip() else {}
        except json.JSONDecodeError as e:
            raise HarnessError(f"controller output not JSON: {p.stdout[:300]} {p.stderr[:300]}") from e
        return data, p.returncode

    def state_path(self, task_id: str) -> Path:
        return task_dir(task_id) / "harness-state.json"

    def init(self, task_id: str, plan: dict) -> dict:
        d = task_dir(task_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "plan.json").write_text(json.dumps(plan, indent=2))
        data, code = self._run("init", "--plan", str(d / "plan.json"), "--state", str(self.state_path(task_id)))
        if code != 0:
            raise HarnessError(f"init failed: {data}")
        return data

    def next(self, task_id: str) -> Directive:
        data, code = self._run("next", "--state", str(self.state_path(task_id)))
        return Directive(data.get("action", "?"), data.get("task"), data, code)

    def record_execute(self, task_id: str, pt: str, ok: bool) -> dict:
        data, _ = self._run("record", "--state", str(self.state_path(task_id)), "--task", pt,
                            "--phase", "execute", "--exit-code", "0" if ok else "1")
        return data

    def verify(self, task_id: str, pt: str) -> tuple[dict, int]:
        return self._run("verify", "--state", str(self.state_path(task_id)), "--task", pt, "--cwd", str(ROOT))

    def close(self, task_id: str, waivers: dict[str, str] | None = None) -> tuple[dict, int]:
        """Waivers come only from the owner at G4."""
        args = ["close", "--state", str(self.state_path(task_id))]
        for pt, reason in (waivers or {}).items():
            args += ["--waive", pt, "--reason", reason]
        return self._run(*args)

    def status(self, task_id: str) -> dict:
        data, _ = self._run("status", "--state", str(self.state_path(task_id)))
        return data
