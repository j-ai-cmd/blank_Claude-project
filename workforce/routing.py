"""Deterministic skill routing (config/skills.yaml). The model never picks skills."""
from __future__ import annotations

import os
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
    support: list[str]          # may be referenced by loaded skills
    checks: list[str]           # route checks + always
    adapters: dict[str, dict]   # per loaded skill
    scope: str | None = None    # only these steps of the skills run
    output: str | None = None   # required primary output format


def resolve(cfg: Config, employee_id: str, task_type: str | None, skill_required: bool = False,
            brand_kit: bool = False) -> ResolvedRoute:
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
    if not brand_kit:
        checks = [c for c in checks if (cfg.checks["checks"].get(c) or {}).get("requires") != "brand_kit"]
    return ResolvedRoute(employee_id, task_type, skills, list(cfg.support_skills(employee_id)), checks,
                         {s: cfg.adapter(s) for s in skills}, r.scope, r.output)


def skill_text(name: str, skills_dir: Path = SKILLS_DIR) -> str:
    p = skills_dir / name / "SKILL.md"
    return p.read_text() if p.exists() else ""


def route_catalog(cfg: Config, employee_id: str) -> list[dict]:
    """What a Lead sees about a specialist: task types, skills, required inputs and runtime."""
    out = []
    for t, r in cfg.routes(employee_id).items():
        out.append({"task_type": t, "skills": list(r.skills), "output": r.output, "needs_input_from": list(r.upstream_from),
                    "needs_runtime": r.requires})
    return out
