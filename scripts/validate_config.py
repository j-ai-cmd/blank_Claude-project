#!/usr/bin/env python3
"""Validate config/*.yaml + schemas/*.json against the design rules.

Exit 0 = clean. Every error is a design contradiction to fix before building.
"""
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
TIER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}
MAX_ROSTER = 20  # Managed Agents coordinator roster limit

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def flatten(items):
    out = []
    for i in items or []:
        out.extend(flatten(i) if isinstance(i, list) else [i])
    return out


def employees(org):
    for key, e in org["core"].items():
        yield dict(e, id=e.get("id", key), dept=None)
    for dept, d in org["departments"].items():
        yield dict(d["lead"], dept=dept)
        for sp in d["specialists"]:
            yield dict(sp, dept=dept)


def main() -> int:
    org = yaml.safe_load((ROOT / "config/org.yaml").read_text())
    perm = yaml.safe_load((ROOT / "config/permissions.yaml").read_text())
    mem = yaml.safe_load((ROOT / "config/memory.yaml").read_text())
    for f in sorted((ROOT / "schemas").glob("*.json")):
        try:
            json.loads(f.read_text())
        except json.JSONDecodeError as e:
            err(f"{f.name}: invalid JSON: {e}")

    actions = perm["actions"]
    restricted = {a: k for k, lst in perm.get("restricted_to_kind", {}).items() for a in lst}
    private = set(org["runtime"]["private_data_tools"])
    seen = set()

    for e in employees(org):
        eid, kind = e["id"], e["kind"]
        if eid in seen:
            err(f"duplicate id {eid}")
        seen.add(eid)
        for field in ("name", "model", "max_tier", "tools", "personality", "memory_read"):
            if field not in e:
                err(f"{eid}: missing {field}")
        tools = flatten(e.get("tools"))
        if len(tools) != len(set(tools)):
            err(f"{eid}: duplicate tools")
        max_tier = TIER[e.get("max_tier", "R0")]
        for t in tools:
            if t not in actions:
                err(f"{eid}: tool '{t}' not in permissions.actions")
                continue
            tier = TIER[actions[t]]
            if tier == 4:
                err(f"{eid}: has forbidden (R4) tool {t}")
            if tier > max_tier:
                err(f"{eid}: tool {t} is {actions[t]} > max_tier {e['max_tier']}")
            if t in restricted and restricted[t] != kind:
                err(f"{eid}: tool {t} restricted to kind '{restricted[t]}'")
        if "web.fetch" in tools and private & set(tools):
            if "web.fetch" not in (e.get("tool_constraints") or {}):
                err(f"{eid}: web.fetch together with private-data tools {sorted(private & set(tools))}")
        if kind == "specialist" and e.get("can_delegate"):
            err(f"{eid}: specialist cannot delegate")
        if kind == "specialist" and e.get("proactive") != "never":
            err(f"{eid}: specialist must never be proactive")

    for dept, d in org["departments"].items():
        if len(d["specialists"]) > MAX_ROSTER:
            err(f"{dept}: {len(d['specialists'])} specialists > roster limit {MAX_ROSTER}")
        if dept not in perm["requesters"]["by_department"]:
            err(f"{dept}: missing from permissions.requesters.by_department")
        if dept not in perm["approval_policy"]["approvers"]["dept_managers"]:
            err(f"{dept}: missing from approval_policy.approvers.dept_managers")

    for layer in ("L0_constitution", "L1_dept_playbook", "L2_employee_profile",
                  "L3_employee_private", "L4_task_workspace", "L5_audit"):
        if layer not in mem["layers"]:
            err(f"memory.yaml: missing layer {layer}")
    if "pinned" not in json.loads((ROOT / "schemas/memory_entry.json").read_text())["properties"]:
        err("memory_entry.json: missing 'pinned'")

    # --- skills.yaml
    skills_cfg = yaml.safe_load((ROOT / "config/skills.yaml").read_text())
    on_disk = {d.name for d in (ROOT / ".claude/skills").iterdir() if (d / "SKILL.md").exists()}
    forbidden = set(skills_cfg["skill_runtime"]["routers_forbidden"])
    assigned = set()
    for eid, sk in skills_cfg["employees"].items():
        if eid not in seen:
            err(f"skills.yaml: unknown employee {eid}")
        for name, when in (sk or {}).items():
            assigned.add(name)
            if name not in on_disk:
                err(f"skills.yaml: {eid} -> skill '{name}' not in .claude/skills")
            if name in forbidden:
                err(f"skills.yaml: {eid} -> router skill '{name}' is forbidden")
            if not when:
                err(f"skills.yaml: {eid} -> {name} missing fires_when")
    for eid in seen:
        if eid not in skills_cfg["employees"]:
            err(f"skills.yaml: employee {eid} missing (use {{}} if no skills)")
    parked = {n for group in skills_cfg["unassigned"].values() for n in group}
    for name in sorted(on_disk - assigned - parked):
        err(f"skills.yaml: skill '{name}' neither assigned nor listed as unassigned")
    for name in sorted(assigned & parked):
        err(f"skills.yaml: skill '{name}' both assigned and unassigned")

    for e in errors:
        print("ERROR:", e)
    print(f"{len(errors)} error(s), {len(seen)} employees checked")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
