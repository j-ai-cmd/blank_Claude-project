"""Deterministic skill routing (config/skills.yaml). The model never picks skills."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import runtime
from .config import SKILLS_DIR, Config


RUNTIMES = {"render": "render runtime (RUNTIME_BACKEND: Modal in production)",
            "sandbox": "code sandbox (RUNTIME_BACKEND: Modal in production)"}


class RouteError(Exception):
    pass


@dataclass
class ResolvedRoute:
    employee_id: str
    task_type: str
    skills: list[str]           # loaded in this order
    support: list[str]          # NOT loaded — readable on demand with skill_read
    checks: list[str]           # route checks + always
    adapters: dict[str, dict]   # per loaded skill
    scope: str | None = None    # only these steps of the skills run
    output: str | None = None   # required primary output format


def resolve(cfg: Config, employee_id: str, task_type: str | None, skill_required: bool = False) -> ResolvedRoute:
    routes = cfg.routes(employee_id)
    if not task_type:
        if skill_required:
            raise RouteError("skill_required but no task_type")
        return ResolvedRoute(employee_id, "", [], [], list(cfg.always_checks), {})
    if task_type not in routes:
        raise RouteError(f"task_type '{task_type}' is not a route of {employee_id}; valid: {sorted(routes)}")
    r = routes[task_type]
    if r.requires in RUNTIMES and not runtime.available(r.requires):
        # fail at contract time: its checks can't run, so it would burn 3 attempts and escalate
        raise RouteError(f"route '{task_type}' needs the {RUNTIMES[r.requires]}, which isn't set up yet — "
                         "tell the owner instead of planning it")
    skills = list(r.run)
    checks = [c for c in r.checks]
    for c in cfg.always_checks:
        if c not in checks:
            checks.append(c)
    if r.pii_allowed:
        checks = [c for c in checks if c != "pii_absent"]
    return ResolvedRoute(employee_id, task_type, skills, list(cfg.support_skills(employee_id)), checks,
                         {s: cfg.adapter(s, r) for s in skills}, r.scope, r.output)


def skill_path(name: str, skills_dir: Path = SKILLS_DIR) -> Path:
    """"sherlock" -> sherlock/SKILL.md; "sherlock#build" -> sherlock/slices/build.md (one role's part only)."""
    base, _, part = name.partition("#")
    return skills_dir / base / ("slices/" + part + ".md" if part else "SKILL.md")


def skill_text(name: str, skills_dir: Path = SKILLS_DIR) -> str:
    p = skill_path(name, skills_dir)
    return p.read_text() if p.exists() else ""


def readable_skills(route: "ResolvedRoute") -> set[str]:
    """Skills an employee may open with skill_read: its loaded skills (their own reference files) + support."""
    return {s.split("#")[0] for s in route.skills} | {s for s in route.support if s != "*"}


def skill_catalog(skills_dir: Path = SKILLS_DIR) -> str:
    """Names + one-line descriptions of the installed library (Mason maps new employees onto it)."""
    import re
    rows = []
    for d in sorted(p for p in skills_dir.iterdir() if (p / "SKILL.md").exists()):
        m = re.search(r"^description:\s*(.+)$", (d / "SKILL.md").read_text(), re.M)
        rows.append(f"- {d.name}: {(m.group(1) if m else '').strip()[:240]}")
    return "\n".join(rows)


def route_catalog(cfg: Config, employee_id: str, show: str | None = None) -> list[dict]:
    """What a Lead sees about a specialist: task types, skills, required inputs and runtime. On a show task the
    inputs list names only that show's employees (another show's roster never leaks into the prompt)."""
    from .prompts import show_allowed
    out = []
    for t, r in cfg.routes(employee_id).items():
        ups = [u for u in r.upstream_from if u == "owner" or u not in cfg.employees
               or show_allowed(cfg, cfg.employees[u], show) or cfg.employees[u].dept != cfg.employees[employee_id].dept]
        out.append({"task_type": t, "skills": list(r.skills), "output": r.output, "needs_input_from": ups,
                    "needs_runtime": r.requires})
    return out
