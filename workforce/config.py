"""Loads the hardcoded design (config/*.yaml) into typed objects the Dispatcher enforces."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("WORKFORCE_ROOT", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "config"
SKILLS_DIR = ROOT / ".claude" / "skills"
CONTEXT_DIR = ROOT / "context"   # context/<employee_id>.md — each employee's training, loaded only into its own sessions

TIER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}


def _flatten(items: Any) -> list[str]:
    out: list[str] = []
    for i in items or []:
        out.extend(_flatten(i) if isinstance(i, list) else [i])
    return out


@dataclass(frozen=True)
class Employee:
    id: str
    name: str
    kind: str  # lead | specialist | router | verifier | librarian
    dept: str | None
    model: str
    max_tier: str
    tools: tuple[str, ...]
    memory_read: tuple[str, ...]
    does: tuple[str, ...] = ()
    does_not: tuple[str, ...] = ()
    personality: dict = field(default_factory=dict)
    tool_constraints: dict = field(default_factory=dict)
    channel: str | None = None
    hard_rules: tuple[str, ...] = ()
    show: str | None = None          # bound to exactly one show (I1/I5), or None
    probation: bool = False          # a new hire: Vera grades its work until you end probation

    @property
    def max_tier_level(self) -> int:
        return TIER[self.max_tier]


@dataclass(frozen=True)
class Route:
    task_type: str
    run: tuple[str, ...]
    checks: tuple[str, ...]
    requires: str | None = None      # runtime this route needs: render | sandbox
    upstream_from: tuple[str, ...] = ()   # plan must feed it an output made by one of these employees
    scope: str | None = None              # which steps of the loaded skills this route runs (writer vs producer)
    output: str | None = None             # the primary output's format — the route's checks run on it
    pii_allowed: bool = False        # deliverable legitimately holds contact details (drops pii_absent)

    @property
    def skills(self) -> tuple[str, ...]:
        return self.run

    @property
    def needs_upstream(self) -> bool:
        return bool(self.upstream_from)


HIRE_DEFAULTS = {"kind": "specialist", "model": "claude-haiku-4-5", "can_delegate": False, "proactive": "never",
                 "memory_read": ["L0", "L1_own_dept", "L3_self", "L4_assigned_handoff_only"]}


def merge_hires(config_dir: Path, org: dict, skills: dict) -> None:
    """config/hires.yaml: employees you hired through Talent. Merged in as specialists of their department."""
    p = config_dir / "hires.yaml"
    if not p.exists():
        return
    for e in (yaml.safe_load(p.read_text()) or {}).get("employees", []):
        raw = {**HIRE_DEFAULTS, **{k: v for k, v in e.items() if k not in ("routes", "new_skills", "department")}}
        org["departments"][e["department"]]["specialists"].append(raw)
        skills["employees"][e["id"]] = {"routes": e.get("routes") or []}


class Config:
    """Immutable view over the six config files. Reload by constructing a new instance."""

    def __init__(self, config_dir: Path = CONFIG_DIR):
        self.dir = config_dir
        load = lambda n: yaml.safe_load((config_dir / n).read_text())  # noqa: E731
        self.org = load("org.yaml")
        self.permissions = load("permissions.yaml")
        self.memory = load("memory.yaml")
        self.skills = load("skills.yaml")
        self.checks = load("checks.yaml")
        self.harness = load("harness.yaml")
        self.constitution = (config_dir / "constitution.md").read_text()
        merge_hires(config_dir, self.org, self.skills)
        self.employees: dict[str, Employee] = {}
        self.dept_channels: dict[str, str] = {}  # "#studio" -> "studio"
        self.leads: dict[str, str] = {}  # dept -> lead id
        self._load_employees()

    # ------------------------------------------------------------------ employees
    def _mk(self, raw: dict, eid: str, dept: str | None, channel: str | None = None) -> Employee:
        return Employee(
            id=eid,
            name=raw["name"],
            kind=raw["kind"],
            dept=dept,
            model=raw["model"],
            max_tier=raw["max_tier"],
            tools=tuple(_flatten(raw.get("tools"))),
            memory_read=tuple(raw.get("memory_read", [])),
            does=tuple(raw.get("does", [])),
            does_not=tuple(raw.get("does_not", [])),
            personality=raw.get("personality", {}),
            tool_constraints=raw.get("tool_constraints", {}) or {},
            channel=channel or raw.get("channel"),
            hard_rules=tuple(raw.get("hard_rules", [])),
            show=raw.get("show") or raw.get("lane"),
            probation=bool(raw.get("probation", False)),
        )

    def _load_employees(self) -> None:
        for key, raw in self.org["core"].items():
            self.employees[key] = self._mk(raw, raw.get("id", key), None)
        for dept, d in self.org["departments"].items():
            lead = self._mk(d["lead"], d["lead"]["id"], dept, d["channel"])
            lead = Employee(**{**lead.__dict__, "hard_rules": tuple(d.get("hard_rules", []))})
            self.employees[lead.id] = lead
            self.leads[dept] = lead.id
            self.dept_channels[d["channel"]] = dept
            for sp in d["specialists"]:
                e = self._mk(sp, sp["id"], dept)
                self.employees[e.id] = Employee(**{**e.__dict__, "hard_rules": tuple(d.get("hard_rules", []))})

    def employee(self, eid: str) -> Employee:
        return self.employees[eid]

    def specialists_of(self, dept: str) -> list[Employee]:
        return [e for e in self.employees.values() if e.dept == dept and e.kind == "specialist"]

    @property
    def owner_id(self) -> str:
        return os.environ.get("OWNER_SLACK_ID") or self.org.get("owner_slack_id", "U_OWNER")

    # ------------------------------------------------------------------ permissions
    def action_tier(self, action: str) -> str | None:
        return self.permissions["actions"].get(action)

    def restricted_kind(self, action: str) -> str | None:
        for kind, lst in self.permissions.get("restricted_to_kind", {}).items():
            if action in lst:
                return kind
        return None

    @property
    def private_data_tools(self) -> set[str]:
        return set(self.org["runtime"]["private_data_tools"])

    # ------------------------------------------------------------------ skills
    def routes(self, eid: str) -> dict[str, Route]:
        cfg = (self.skills["employees"].get(eid) or {})
        out = {}
        for r in cfg.get("routes", []) or []:
            out[r["task_type"]] = Route(
                task_type=r["task_type"],
                run=tuple(r.get("run", [])),
                checks=tuple(r.get("checks", [])),
                requires=r.get("requires"),
                upstream_from=tuple(r.get("upstream_from") or ()),
                scope=r.get("scope"),
                output=r.get("output"),
                pii_allowed=bool(r.get("pii_allowed", False)),
            )
        return out

    def support_skills(self, eid: str) -> tuple[str, ...]:
        return tuple((self.skills["employees"].get(eid) or {}).get("support", []) or [])

    def adapter(self, skill: str) -> dict:
        return (self.skills.get("adapters") or {}).get(skill, {}) or {}

    def phase_skills(self, emp: "Employee", phase: str) -> list[str]:
        return list(((self.skills.get("phase_skills") or {}).get(emp.kind) or {}).get(phase) or [])

    # ------------------------------------------------------------------ shows + lanes (isolation I1-I5)
    @property
    def shows(self) -> dict:
        """Every isolated lane: the video shows plus non-video lanes (e.g. company). Same rules for all."""
        out = {k: {**v, "kind": "show", "shared": list(self.org.get("show_shared") or [])}
               for k, v in (self.org.get("shows") or {}).items()}
        for k, v in (self.org.get("lanes") or {}).items():
            out[k] = {**v, "kind": "lane", "shared": list(v.get("shared") or [])}
        return out

    def shows_named(self, text: str) -> list[str]:
        """Shows/lanes the owner's own text names: the trigger next to a context word ('jai reel', 'company api
        bug'), or 'show: <name>' / 'lane: <name>'. A bare name ('pitch Peter at Acme') names nothing."""
        import re
        media = ["reels?", "videos?", "shorts?", "scripts?", "captions?", "thumbnails?", "covers?", "episodes?",
                 "shows?", "visuals?", "stor(?:y|ies)"]
        out = []
        for name, spec in self.shows.items():
            near = "(?:" + "|".join(media if spec["kind"] == "show" else [re.escape(w) for w in spec.get("near", [])]) + ")"
            for w in spec.get("triggers", []):
                t = re.escape(w)
                if re.search(rf"\b(?:show|lane)\s*[:=]\s*{re.escape(name)}\b", text or "", re.I) or (
                        re.search(rf"\b{t}\b", text or "", re.I) and (
                            " " in w or re.search(rf"\b{t}\b(?:\W+[\w']+){{0,3}}?\W+{near}\b|"
                                                  rf"\b{near}\b(?:\W+[\w']+){{0,3}}?\W+{t}\b", text or "", re.I))):
                    out.append(name)
                    break
        return out

    def show_bible(self, show: str) -> str:
        d = ROOT / str(self.shows.get(show, {}).get("bible_dir", ""))
        if not show or not d.is_dir():
            return ""
        return "\n\n".join(f"## {p.name}\n{p.read_text(errors='replace')[:20_000]}" for p in sorted(d.glob("*.md")))

    def context(self, eid: str) -> str:
        p = self.dir.parent / "context" / f"{eid}.md"
        return p.read_text() if p.exists() else ""

    def owner_facts(self, eid: str) -> str:
        """The '## Owner facts' section of an employee's training file: the owner's own words, citable as context:<id>."""
        txt = self.context(eid)
        if "## Owner facts" not in txt:
            return ""
        body = txt.split("## Owner facts", 1)[1].split("\n## ", 1)[0]
        lines = [x for x in body.strip().splitlines() if x.strip() and not x.strip().startswith("_")]
        return "\n".join(lines)

    def auto_start_small(self, dept: str) -> bool:
        return bool((self.org["departments"].get(dept) or {}).get("auto_start_small", True))

    @property
    def always_checks(self) -> list[str]:
        return list(self.checks.get("always", []))


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
