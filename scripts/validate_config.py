#!/usr/bin/env python3
"""Validate config/*.yaml + schemas/*.json against the design rules.

Exit 0 = clean. Every error is a design contradiction to fix before building.
"""
import json
import pathlib
import re
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
    sys.path.insert(0, str(ROOT))
    from workforce.config import merge_hires
    skills_early = yaml.safe_load((ROOT / "config/skills.yaml").read_text())
    merge_hires(ROOT / "config", org, skills_early)
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
        show = e.get("show")
        if show and kind != "specialist":
            err(f"{eid}: only specialists are bound to a show")
        lanes = {**(org.get("shows") or {}), **(org.get("lanes") or {})}
        show = show or e.get("lane")
        if show is not None and show not in lanes:
            err(f"{eid}: unknown show/lane '{show}'")
        if "voice.synthesize" in tools and show and (lanes[show].get("voice", "none") in ("none", "owner_recorded")):
            err(f"{eid}: show '{show}' has no voice but the employee holds voice.synthesize")
        if not (ROOT / "context" / f"{eid}.md").exists():
            err(f"{eid}: missing training file context/{eid}.md")
        else:
            ctx = (ROOT / "context" / f"{eid}.md").read_text()
            for sec in ("## Role", "## Fire when", "## Skills", "## Never", "## Owner must provide"):
                if sec not in ctx:
                    err(f"context/{eid}.md: missing section '{sec}'")
            skills_cfg_ = yaml.safe_load((ROOT / "config/skills.yaml").read_text())
            for r in ((skills_cfg_["employees"].get(eid) or {}).get("routes") or []):
                if f"`{r['task_type']}`" not in ctx:
                    err(f"context/{eid}.md: route `{r['task_type']}` not documented (when to fire it)")
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

    # --- skills.yaml (routing) + checks.yaml + harness
    skills_cfg = skills_early
    checks_cfg = yaml.safe_load((ROOT / "config/checks.yaml").read_text())["checks"]
    skill_dir = ROOT / ".claude/skills"
    on_disk = {d.name for d in skill_dir.iterdir() if (d / "SKILL.md").exists()}
    forbidden = set(skills_cfg["skill_runtime"].get("routers_forbidden") or [])
    adapters = skills_cfg.get("adapters", {})
    conflicts = skills_cfg.get("conflicts", [])
    deps = {}
    for n in on_disk:
        txt = (skill_dir / n / "SKILL.md").read_text()
        deps[n] = {m for m in re.findall(r"(?<![\w/.-])/([a-z0-9-]+)", txt) if m in on_disk and m != n}
    assigned = set()
    owner_of_type: dict[str, str] = {}
    kinds = {e["id"]: e["kind"] for e in employees(org)}
    for kind_, phases in (skills_cfg.get("phase_skills") or {}).items():
        for ph, names in phases.items():
            for name in names:
                assigned.add(name)
                if name not in on_disk:
                    err(f"skills.yaml: phase skill {kind_}/{ph} -> '{name}' not in .claude/skills")
    for eid, cfg in skills_cfg["employees"].items():
        if (cfg or {}).get("routes") and kinds.get(eid) != "specialist":
            err(f"skills.yaml: {eid} is a {kinds.get(eid)} — only specialists run routes (use phase_skills)")
        for r in (cfg or {}).get("routes", []):
            if r["task_type"] in owner_of_type:
                err(f"skills.yaml: task_type '{r['task_type']}' owned by both {owner_of_type[r['task_type']]} and {eid} (I2)")
            owner_of_type[r["task_type"]] = eid
        if eid not in seen:
            err(f"skills.yaml: unknown employee {eid}")
        cfg = cfg or {}
        support = set(cfg.get("support", []))
        mods = {}
        types = [r["task_type"] for r in cfg.get("routes", [])]
        if len(types) != len(set(types)):
            err(f"skills.yaml: {eid} duplicate task_type")
        for m, spec in mods.items():
            for t in spec.get("applies_to", []):
                if t not in types:
                    err(f"skills.yaml: {eid} modifier {m} applies to unknown route {t}")
        for r in cfg.get("routes", []):
            loaded = list(r.get("run", [])) + list(r.get("also", []))
            loaded_mod = [m for m, spec in mods.items() if r["task_type"] in spec.get("applies_to", [])]
            for name in loaded + loaded_mod + list(support):
                assigned.add(name)
                if name not in on_disk:
                    err(f"skills.yaml: {eid}/{r['task_type']} -> '{name}' not in .claude/skills")
                if name in forbidden:
                    err(f"skills.yaml: {eid} -> router '{name}' forbidden")
            available = set(loaded) | set(loaded_mod) | support
            for name in ([] if r.get("scope") else loaded + loaded_mod + sorted(support)):   # scoped routes run only named steps
                adapter_txt = str(adapters.get(name, ""))
                for d in deps.get(name, set()) - available:
                    if d not in adapter_txt:
                        err(f"skills.yaml: {eid}/{r['task_type']}: '{name}' calls '/{d}' which this employee can't load")
            ids = r.get("checks", [])
            if not ids:
                err(f"skills.yaml: {eid}/{r['task_type']} has no checks (harness would self-verify)")
            for c in ids:
                if c not in checks_cfg:
                    err(f"skills.yaml: {eid}/{r['task_type']} unknown check '{c}'")
                elif checks_cfg[c].get("kind") != "executable":
                    err(f"skills.yaml: {eid}/{r['task_type']} lists non-executable check '{c}' (Dispatcher adds those)")
            for g in conflicts:
                hit = [n for n in loaded + loaded_mod if n in g["group"]]
                if len(hit) > 1:
                    order = g.get("order")
                    if not order:
                        err(f"skills.yaml: {eid}/{r['task_type']} loads conflicting {hit}")
                    elif [n for n in order if n in hit] != [n for n in hit]:
                        err(f"skills.yaml: {eid}/{r['task_type']} {hit} not in required order {order}")
    for eid in seen:
        if eid not in skills_cfg["employees"]:
            err(f"skills.yaml: employee {eid} missing (use {{routes: []}})")
    engine = set(skills_cfg.get("system_engine", []))
    parked = {n for group in skills_cfg["unassigned"].values() for n in group}
    for name in sorted(on_disk - assigned - parked - engine):
        err(f"skills.yaml: skill '{name}' neither assigned, engine, nor parked")
    for name in sorted((assigned | engine) & parked):
        err(f"skills.yaml: skill '{name}' both used and parked")
    if not any(c.get("kind") == "executable" for k, c in checks_cfg.items()
               if k in yaml.safe_load((ROOT / "config/checks.yaml").read_text())["always"]):
        err("checks.yaml: `always` must contain an executable check")

    for show, spec in {**(org.get("shows") or {}), **(org.get("lanes") or {})}.items():
        members = [e["id"] for e in employees(org) if (e.get("show") or e.get("lane")) == show]
        for sh in (spec.get("shared") or []) + (list(org.get("show_shared") or []) if show in (org.get("shows") or {}) else []):
            if sh not in seen:
                err(f"{show}: shared helper {sh} is not an employee")
        if not members:
            err(f"show {show}: no employees")
        if not spec.get("triggers"):
            err(f"show {show}: needs trigger words")
    for x in (ROOT / "context").glob("*.md"):
        if x.stem not in seen:
            err(f"context/{x.name}: no such employee (stale training file)")

    for e in errors:
        print("ERROR:", e)
    print(f"{len(errors)} error(s), {len(seen)} employees checked")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
