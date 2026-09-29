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

    @property
    def max_tier_level(self) -> int:
        return TIER[self.max_tier]


@dataclass(frozen=True)
class Route:
    task_type: str
    run: tuple[str, ...]
    also: tuple[str, ...]
    checks: tuple[str, ...]
    disabled: str | None = None
    requires: str | None = None
    trigger_word: str | None = None
    explicit_only: bool = False

    @property
    def skills(self) -> tuple[str, ...]:
        return self.run + self.also


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
        self.employees: dict[str, Employee] = {}
        self.dept_channels: dict[str, str] = {}  # "#marketing" -> "marketing"
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
                also=tuple(r.get("also", [])),
                checks=tuple(r.get("checks", [])),
                disabled=r.get("disabled"),
                requires=r.get("requires"),
                trigger_word=r.get("trigger_word"),
                explicit_only=bool(r.get("explicit_only", False)),
            )
        return out

    def modifiers(self, eid: str) -> dict:
        return (self.skills["employees"].get(eid) or {}).get("modifiers", {}) or {}

    def support_skills(self, eid: str) -> tuple[str, ...]:
        return tuple((self.skills["employees"].get(eid) or {}).get("support", []) or [])

    def adapter(self, skill: str) -> dict:
        return (self.skills.get("adapters") or {}).get(skill, {}) or {}

    @property
    def always_checks(self) -> list[str]:
        return list(self.checks.get("always", []))


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
