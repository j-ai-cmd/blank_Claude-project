"""Deterministic skill routing (config/skills.yaml). The model never picks skills."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

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
    drop: dict[str, list[str]] | None = None   # skill -> section headings left out of the prompt


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
                         {s: cfg.adapter(s) for s in skills}, r.scope, r.output, dict(r.drop))


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            try:
                meta = yaml.safe_load(raw[3:end]) or {}
            except yaml.YAMLError:
                meta = {}
            return (meta if isinstance(meta, dict) else {}), raw[end + 4:].lstrip("\n")
    return {}, raw


def skill_text(name: str, skills_dir: Path = SKILLS_DIR) -> str:
    """The skill's instructions without its YAML frontmatter (the description is for routing, not for the agent)."""
    p = skills_dir / name / "SKILL.md"
    return _split_frontmatter(p.read_text())[1] if p.exists() else ""


HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _sections(text: str) -> list[tuple[int, str, list[str]]]:
    """(level, heading, lines) blocks split at markdown headings that sit outside ``` fences."""
    out: list[tuple[int, str, list[str]]] = [(0, "", [])]
    fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else HEADING.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2).strip(), [line]))
        else:
            out[-1][2].append(line)
    return out


def trim_sections(text: str, drop: list[str]) -> str:
    """Remove the sections whose heading starts with one of `drop` (case-insensitive), with their sub-sections."""
    if not drop:
        return text
    keep, cut_level = [], None
    for level, head, lines in _sections(text):
        if cut_level is not None and level > cut_level:
            continue
        cut_level = None
        if level and any(head.lower().startswith(d.lower()) for d in drop):
            cut_level = level
            continue
        keep.extend(lines)
    return "\n".join(keep)


def skill_brief(name: str, skills_dir: Path = SKILLS_DIR) -> str:
    """An on-demand skill's stand-in: what it is for + its table of contents (open sections with skill_read)."""
    p = skills_dir / name / "SKILL.md"
    if not p.exists():
        return ""
    meta, body = _split_frontmatter(p.read_text())
    heads = [f"{'  ' * (lvl - 1)}- {h}" for lvl, h, _ in _sections(body) if 1 <= lvl <= 3]
    return (" ".join(str(meta.get("description", "")).split()) + "\nContents of SKILL.md:\n" + "\n".join(heads)).strip()


SKILL_FILE_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html", ".css", ".js", ".mjs", ".ts", ".py", ".sh"}
MAX_SKILL_FILE_CHARS = 40_000


def skill_files(name: str, skills_dir: Path = SKILLS_DIR) -> list[str]:
    """Text files inside one skill folder (its references/, scripts/, PROCESS.md …), relative to the folder."""
    d = skills_dir / name
    if not d.is_dir():
        return []
    return sorted(str(p.relative_to(d)) for p in d.rglob("*")
                  if p.is_file() and p.suffix.lower() in SKILL_FILE_SUFFIXES and "node_modules" not in p.parts)


def skill_file(name: str, rel: str, skills_dir: Path = SKILLS_DIR) -> str | None:
    """One file of a skill, read on demand (progressive disclosure). None if it isn't inside that skill."""
    d = (skills_dir / name).resolve()
    p = (d / (rel or "SKILL.md")).resolve()
    if d not in p.parents or not p.is_file() or p.suffix.lower() not in SKILL_FILE_SUFFIXES:
        return None
    return p.read_text(errors="replace")[:MAX_SKILL_FILE_CHARS]


def route_catalog(cfg: Config, employee_id: str) -> list[dict]:
    """What a Lead sees about a specialist: WHO does WHAT — task types, what each produces and whose output it
    needs. Never the skills or how the work is done: that is the specialist's context, not the Lead's."""
    out = []
    for t, r in cfg.routes(employee_id).items():
        row = {"task_type": t}
        if r.output:
            row["output"] = r.output
        if r.upstream_from:
            row["needs_input_from"] = list(r.upstream_from)
        if r.shows:   # where it may run ("none" = a task that names no show) — saves a rejected-plan retry
            row["only_for"] = list(r.shows)
        out.append(row)
    return out
