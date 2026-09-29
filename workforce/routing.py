"""Deterministic skill routing (config/skills.yaml). The model never picks skills."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import SKILLS_DIR, Config


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


def resolve(cfg: Config, employee_id: str, task_type: str | None, style_tags: list[str] | None = None,
            skill_required: bool = False, brand_kit: bool = False) -> ResolvedRoute:
    routes = cfg.routes(employee_id)
    if not task_type:
        if skill_required:
            raise RouteError("skill_required but no task_type")
        return ResolvedRoute(employee_id, "", [], [], list(cfg.always_checks), {})
    if task_type not in routes:
        raise RouteError(f"task_type '{task_type}' is not a route of {employee_id}; valid: {sorted(routes)}")
    r = routes[task_type]
    if r.disabled:
        raise RouteError(f"route '{task_type}' is disabled: {r.disabled}")
    if r.requires == "brand_kit" and not brand_kit:
        raise RouteError(f"route '{task_type}' requires the brand kit, which isn't added yet")
    skills = list(r.run) + [s for s in r.also if s not in r.run]
    tags = {t.lower() for t in (style_tags or [])}
    for mod, spec in cfg.modifiers(employee_id).items():
        if task_type in spec.get("applies_to", []) and tags & {t.lower() for t in spec.get("if_style_tags_any", [])}:
            if mod not in skills:
                skills.append(mod)
    checks = [c for c in r.checks]
    for c in cfg.always_checks:
        if c not in checks:
            checks.append(c)
    if not brand_kit:
        checks = [c for c in checks if (cfg.checks["checks"].get(c) or {}).get("requires") != "brand_kit"]
    return ResolvedRoute(employee_id, task_type, skills, list(cfg.support_skills(employee_id)), checks,
                         {s: cfg.adapter(s) for s in skills})


def skill_text(name: str, skills_dir: Path = SKILLS_DIR) -> str:
    p = skills_dir / name / "SKILL.md"
    return p.read_text() if p.exists() else ""


def route_catalog(cfg: Config, employee_id: str) -> list[dict]:
    """What a Lead sees about a specialist: task types + skills + disabled flags (for G1 cards too)."""
    out = []
    for t, r in cfg.routes(employee_id).items():
        out.append({"task_type": t, "skills": list(r.skills), "disabled": r.disabled,
                    "explicit_only": r.explicit_only, "trigger_word": r.trigger_word})
    return out
