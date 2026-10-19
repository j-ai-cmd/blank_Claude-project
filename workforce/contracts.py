"""Contract drafting, planning and their validation (G1 and the plan check)."""
from __future__ import annotations

import json
import re

from . import states
from .agents import ToolSpec, err, ok
from .config import Config, Employee, TIER
from .db import Approval, AuditEvent, Task
from .dispatch_common import CRITERION_CHECKS, INFRA, SIZE_LIMIT, _id, normalize_ids
from .live import OWNER
from .prompts import owner_request, phase_block, show_allowed, system_prompt
from .routing import RouteError, resolve
from .slack import approval_blocks


class ContractsMixin:
    # ================================================================== contract (G1)
    def _drafter(self, task: Task) -> Employee:
        if task.department == "hq":
            return self.cfg.employee("chief_of_staff")
        return self.cfg.employee(self.cfg.leads[task.department])

    def _owner_text(self, t: Task) -> str:
        """Only the owner's own words count for explicit-only triggers — never text a Lead wrote for a sub-task (C31)."""
        with self.Session() as db:
            root = t
            while root.parent_id:
                root = db.get(Task, root.parent_id)
            return " ".join([root.original_request] + list((root.contract or {}).get("_owner_notes", [])))

    async def draft_contract(self, task_id: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            emp = self._drafter(t)
            prompt = owner_request(t.id, t.original_request)
            for i, n in enumerate((t.contract or {}).get("_owner_notes", [])):
                prompt += "\n" + owner_request(f"{t.id}-note{i}", n)
            lead_session = emp.kind == "lead"
            system = system_prompt(self.cfg, emp, "contract", None,
                                   self.memory.read(db, emp, t.original_request, show=t.show), show=t.show,
                                   session=lead_session)
            db.commit()
        sink: dict = {}
        if lead_session:
            res = await self._run(emp, task_id, "contract", system, phase_block(self.cfg, emp, "contract") + "\n\n" + prompt,
                                  self._lead_tools(emp, task_id, "contract", sink), session=True)
        else:
            res = await self._run(emp, task_id, "contract", system, prompt, [self._submit_contract_tool(emp, task_id, sink)])
        with self.Session() as db:
            t = db.get(Task, task_id)
            if "contract" not in sink:
                why = (res.errors or [res.text])[0] if (res.errors or res.text) else "no output"
                if res.is_error and INFRA.search(str(why)):   # not the owner's wording: the Claude link itself failed
                    self._post(t, None, f"⚠️ Couldn't reach Claude ({why[:200]}). Check CLAUDE_CODE_OAUTH_TOKEN / the "
                                        "network, then reply 'retry' here.")
                else:
                    self._post(t, emp, f"I couldn't draft a contract ({why}). Please rephrase or add detail.")
                db.commit()
                return
            c = sink["contract"]
            c["_owner_notes"] = (t.contract or {}).get("_owner_notes", [])
            states.new_contract_version(db, t, c, emp.id)
            t.size = c["size"]
            states.transition(db, t, "CONTRACT_DRAFTED", emp.id)
            auto = (c["size"] == "S" and not c.get("questions") and self.cfg.auto_start_small(t.department)
                    and not any(TIER.get(x, 0) >= 2 for x in c.get("planned_actions_tiers", [])))
            body = self._contract_text(c, t.show)
            if auto:
                t.g1_approval_id = f"auto-S-{t.id}-v{t.contract_version}"
                states.transition(db, t, "CONTRACT_APPROVED", "policy", "S task auto-start")
                db.commit()
                self._post(t, emp, "*Contract (small task — starting now; reply here to change it)*\n" + body)
                await self.plan(task_id)
                return
            a = Approval(id=_id("apr"), task_id=t.id, gate="G1", contract_version=t.contract_version,
                         preview={"contract": c})
            db.add(a)
            db.commit()
            self._post(t, emp, "Contract ready for approval", blocks=approval_blocks(
                f"G1 · Contract v{t.contract_version}", body, a.id))
            self.live.approval_requested(a.id, t.id, "G1", emp.id, f"Contract v{t.contract_version}", body)
            self.live.handoff(t.id, emp.id, OWNER, "approval_request", c["objective"], gate="G1", approval_id=a.id)

    def _submit_contract_tool(self, emp: Employee, task_id: str, sink: dict) -> ToolSpec:
        schema = {"type": "object", "properties": {
            "objective": {"type": "string"},
            "deliverables": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "description": {"type": "string"}, "format": {"type": "string"},
                "assignee": {"type": "string"}, "task_type": {"type": "string"}},
                "required": ["id", "description", "assignee", "task_type"]}},
            "acceptance_criteria": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "text": {"type": "string"},
                "check": {"type": "string", "enum": sorted(CRITERION_CHECKS)}}, "required": ["id", "text", "check"]}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "out_of_scope": {"type": "array", "items": {"type": "string"}},
            "deadline": {"type": "string"}, "size": {"type": "string", "enum": ["S", "M", "L"]},
            "planned_actions_tiers": {"type": "array", "items": {"type": "string"}},
            "one_off_instructions": {"type": "array", "items": {"type": "string"}},
            "questions": {"type": "array", "items": {"type": "string"}},
            "departments": {"type": "array", "items": {"type": "object"}},
        }, "required": ["objective", "deliverables", "acceptance_criteria", "size"]}

        async def handler(args: dict) -> dict:
            args = normalize_ids(args)
            with self.Session() as db:
                t0 = db.get(Task, task_id)
                owner_text, show = self._owner_text(t0), t0.show
            problems = validate_contract(args, emp, self.cfg, owner_text, self.brand_kit, show)
            if problems:
                return err("Contract rejected: " + "; ".join(problems) + ". Fix and call submit_contract again.")
            sink["contract"] = args
            return ok("Contract stored. Stop here.")
        return ToolSpec("submit_contract", "Submit the Task Contract (once).", schema, handler)

    async def _adopt_inherited_contract(self, task_id: str, contract: dict) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.new_contract_version(db, t, {**contract, "_inherited": True}, "chief_of_staff")
            t.size = contract.get("size", "M")
            states.transition(db, t, "CONTRACT_DRAFTED", "chief_of_staff")
            t.g1_approval_id = f"inherited-{t.parent_id}"
            states.transition(db, t, "CONTRACT_APPROVED", "policy", "inherits parent G1 (internal sub-task)")
            db.commit()
        await self.plan(task_id)

    def _contract_text(self, c: dict, show: str | None = None) -> str:
        crit = "\n".join(f"{x['id']}. {x['text']} _({x.get('check', 'verifier')})_" for x in c["acceptance_criteria"])
        lines = []
        for d in c["deliverables"]:
            who = ""
            if d.get("assignee"):
                e = self.cfg.employees.get(d["assignee"])
                route = self.cfg.routes(d["assignee"]).get(d.get("task_type") or "")
                skills = ", ".join(route.skills) if route else "no skill"
                who = f" → *{e.name if e else d['assignee']}* · `{d.get('task_type')}` ({skills})"
            lines.append(f"• {d.get('id', '')} {d.get('description', d)}{who}")
        q = ("\n*Questions for you:*\n" + "\n".join(f"• {x}" for x in c["questions"])) if c.get("questions") else ""
        return ((f"*Show:* {show} (only {show}'s own employees)\n" if show else "") +
                f"*Objective:* {c['objective']}\n*Deliverables:*\n" + "\n".join(lines) +
                f"\n*Acceptance criteria:*\n{crit}\n*Size:* {c['size']}  *Deadline:* {c.get('deadline') or '-'}{q}")

    # ================================================================== plan
    async def plan(self, task_id: str, revision_notes: str = "") -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            if t.department == "hq":
                db.commit()
                await self._spawn_children(task_id, t.contract.get("departments") or [], relay_for=None)
                return
            emp = self.cfg.employee(self.cfg.leads[t.department])
            contract = {k: v for k, v in t.contract.items() if not k.startswith("_")}
            prompt = "Approved contract:\n" + json.dumps(contract, indent=1)
            for i, n in enumerate(t.contract.get("_owner_notes", [])):
                prompt += "\n" + owner_request(f"note{i}", n)
            if t.contract.get("_dept_inputs"):
                prompt += ("\n\nArtifacts delivered by other departments (use them via inputs):\n"
                           + json.dumps(t.contract["_dept_inputs"], indent=1))
            if revision_notes:
                prompt += "\n\nREVISION — fix these problems with a changed approach:\n" + revision_notes
            system = system_prompt(self.cfg, emp, "plan", None,
                                   self.memory.read(db, emp, t.original_request, show=t.show), show=t.show, session=True)
            db.commit()
        sink: dict = {}
        await self._run(emp, task_id, "plan", system, phase_block(self.cfg, emp, "plan") + "\n\n" + prompt,
                        self._lead_tools(emp, task_id, "plan", sink), session=True)
        with self.Session() as db:
            t = db.get(Task, task_id)
            if "plan" not in sink:
                to = "CANCELLED" if t.status in ("CONTRACT_APPROVED", "WAITING_ON_DEPT") else "ESCALATED"
                states.transition(db, t, to, emp.id, "lead produced no valid plan")
                db.commit()
                self._post(t, emp, "I couldn't produce a valid plan — stopping here. Reply to give more direction.")
                return
            if sink.get("cross_dept"):
                c = dict(t.contract)
                c["_cross_pending"] = sink["cross_dept"]
                t.contract = c
                states.transition(db, t, "WAITING_ON_DEPT", emp.id, "asked other departments via Chief of Staff")
                db.commit()
                self._post(t, emp, "Waiting on: " + ", ".join(x["department"] for x in sink["cross_dept"]))
                await self._spawn_children(task_id, sink["cross_dept"], relay_for=emp.id)
                return
            t.plan = sink["plan"]
            if t.status in ("CONTRACT_APPROVED", "WAITING_ON_DEPT"):
                states.transition(db, t, "PLANNED", emp.id)
            if t.contract.get("_inherited"):
                # owner never saw assignees at G1 for inherited sub-tasks: show the routing now (visibility)
                self._post(t, emp, "Plan: " + "; ".join(f"{h['to']} · {h['task_type']}" for h in t.plan))
            if t.size == "L" and not revision_notes:
                a = Approval(id=_id("apr"), task_id=t.id, gate="G2", contract_version=t.contract_version,
                             preview={"plan": t.plan})
                db.add(a)
                db.commit()
                body = "\n".join(f"{i}. *{h['to']}* ({h['task_type']}): {h['objective']}" for i, h in enumerate(t.plan, 1))
                self._post(t, emp, "Plan ready", blocks=approval_blocks("G2 · Plan", body, a.id))
                self.live.approval_requested(a.id, t.id, "G2", emp.id, "Plan", body)
                self.live.handoff(t.id, emp.id, OWNER, "approval_request", "plan", gate="G2", approval_id=a.id)
                return
            db.commit()
        await self.execute(task_id)

    def _submit_plan_tool(self, lead: Employee, task_id: str, sink: dict) -> ToolSpec:
        schema = {"type": "object", "properties": {
            "handoffs": {"type": "array", "items": {"type": "object", "properties": {
                "deliverable": {"type": "string"}, "to": {"type": "string"}, "task_type": {"type": "string"},
                "objective": {"type": "string"}, "criteria": {"type": "array", "items": {"type": "string"}},
                "inputs_from": {"type": "array", "items": {"type": "string"}},
                "inputs": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "do_not": {"type": "array", "items": {"type": "string"}}, "context_summary": {"type": "string"},
                "platform": {"type": "string"},
                "spec": {"type": "object"}}, "required": ["to", "task_type", "objective", "criteria"]}},
            "cross_dept": {"type": "array", "items": {"type": "object"}}}}

        async def handler(args: dict) -> dict:
            with self.Session() as db:
                t = db.get(Task, task_id)
                contract, version, size = dict(t.contract), t.contract_version, t.size or "M"
                owner_text, is_child, show = self._owner_text(t), t.parent_id is not None, t.show
            args = normalize_ids(args)
            problems = []
            cross = args.get("cross_dept") or []
            handoffs = args.get("handoffs") or []
            if cross:
                if is_child:
                    problems.append("sub-tasks can't request other departments (one level only)")
                if size == "S":
                    problems.append("S tasks can't involve other departments — ask the owner to re-scope")
                if not self._check(lead, task_id, "cos.request", {"departments": [c.get("department") for c in cross]}).allowed:
                    problems.append("cos.request not permitted")
                for c in cross:
                    if c.get("department") not in self.cfg.org["departments"] or c.get("department") == lead.dept:
                        problems.append(f"cross_dept: bad department {c.get('department')}")
                    crit = c.get("acceptance_criteria") or []
                    if not str(c.get("objective", "")).strip() or not crit or not all(
                            isinstance(x, dict) and x.get("id") and x.get("text") for x in crit):
                        problems.append("cross_dept entries need objective + acceptance_criteria [{id,text}]")
                if problems:
                    return err("Plan rejected: " + "; ".join(problems))
                sink["cross_dept"] = [{**c, "size": c.get("size", "M"), "planned_actions_tiers": c.get("planned_actions_tiers", [])} for c in cross]
                sink["plan"] = []
                return ok("Cross-department request stored. Stop here; you'll resume when they deliver.")
            packets, prob = validate_plan(self.cfg, lead, task_id, contract, version, size, handoffs, owner_text,
                                          self.brand_kit, show)
            if prob:
                return err("Plan rejected: " + "; ".join(prob))
            sink["plan"] = packets
            return ok(f"Plan stored ({len(packets)} handoffs). Stop here.")
        return ToolSpec("submit_plan", "Submit handoff packets (the harness plan), or cross_dept requests.", schema, handler)

    async def _spawn_children(self, task_id: str, children: list[dict], relay_for: str | None) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            if relay_for is None:  # Chief of Staff task
                states.transition(db, t, "PLANNED", "chief_of_staff")
                states.transition(db, t, "IN_PROGRESS", "chief_of_staff", "sub-tasks spawned")
            db.add(AuditEvent(task_id=t.id, actor="chief_of_staff", kind="cos.relay",
                              detail={"for": relay_for, "departments": [c.get("department") for c in children]}))
            db.commit()
            parent = {"id": t.id, "channel": t.slack_channel, "thread": t.slack_thread, "user": t.requested_by,
                      "show": t.show}
        for ch in children:
            sub = {"objective": ch["objective"],
                   "deliverables": ch.get("deliverables") or [{"id": "D1", "description": ch["objective"], "format": "doc"}],
                   "acceptance_criteria": ch["acceptance_criteria"], "size": ch.get("size", "M"),
                   "planned_actions_tiers": ch.get("planned_actions_tiers", [])}
            internal = (all(TIER.get(x, 0) <= 1 for x in sub["planned_actions_tiers"])
                        and self.cfg.auto_start_small(ch["department"]))   # P4: Talent always waits for your G1
            await self.start_task(ch["department"], parent["user"], ch["objective"], parent["channel"],
                                  parent["thread"], parent_id=parent["id"],
                                  inherited_contract=sub if internal else None, show=parent["show"])


def _route_ok(cfg: Config, emp_id: str, task_type: str | None, owner_text: str, brand_kit: bool,
              skill_required=False) -> str | None:
    try:
        resolve(cfg, emp_id, task_type, skill_required, brand_kit)
    except RouteError as e:
        return str(e)
    return None


def _norm(text: str) -> str:
    """Whitespace/quote/case-insensitive form used to check Proof's quotes against the deliverable."""
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", t).strip()


def _show_problem(cfg: Config, emp_id: str, show: str | None) -> str | None:
    """I1: a show's employees only on that show's tasks; non-show helpers never on a show task."""
    e = cfg.employees[emp_id]
    if show_allowed(cfg, e, show):
        return None
    if e.show:
        return (f"{e.name} works only on the '{e.show}' show and fires only when the owner names it"
                + (f" (this task is for '{show}')" if show else " (this task names no show)"))
    return f"{e.name} doesn't work on show tasks — this task is for '{show}'; use that show's own employee"


def validate_contract(c: dict, emp: Employee, cfg: Config, owner_text: str = "", brand_kit: bool = False,
                      show: str | None = None) -> list[str]:
    problems = []
    if not str(c.get("objective", "")).strip():
        problems.append("objective missing")
    if not c.get("deliverables"):
        problems.append("at least one deliverable")
    crit = c.get("acceptance_criteria") or []
    if not crit:
        problems.append("at least one acceptance criterion")
    ids = [x.get("id") for x in crit if isinstance(x, dict)]
    if len(ids) != len(crit) or len(set(ids)) != len(ids) or not all(ids):
        problems.append("every criterion needs a unique id")
    for x in crit:
        if isinstance(x, dict) and x.get("check", "verifier") not in CRITERION_CHECKS:
            problems.append(f"criterion {x.get('id')}: check must be one of {sorted(CRITERION_CHECKS)}")
        if isinstance(x, dict) and not str(x.get("text", "")).strip():
            problems.append(f"criterion {x.get('id')}: text missing")
    if c.get("size") not in ("S", "M", "L"):
        problems.append("size must be S, M or L")
    for tier in c.get("planned_actions_tiers", []) or []:
        if tier not in ("R0", "R1", "R2", "R3"):
            problems.append(f"bad tier {tier}")
    if emp.kind == "router":
        depts = c.get("departments") or []
        if not depts:
            problems.append("Chief of Staff contracts must list departments[] with objective + acceptance_criteria")
        for d in depts:
            if d.get("department") not in cfg.org["departments"]:
                problems.append(f"unknown department {d.get('department')}")
            if not d.get("acceptance_criteria"):
                problems.append(f"{d.get('department')}: acceptance_criteria required")
        return problems
    # C6: every deliverable names its specialist + task_type (owner approves the skill choice at G1)
    specialists = {s.id for s in cfg.specialists_of(emp.dept or "")}
    d_ids = [d.get("id") for d in c.get("deliverables") or [] if isinstance(d, dict)]
    if len(set(d_ids)) != len(d_ids) or not all(d_ids):
        problems.append("every deliverable needs a unique id")
    assignees = set()
    for d in c.get("deliverables") or []:
        if not isinstance(d, dict):
            problems.append("deliverables must be objects")
            continue
        if d.get("assignee") not in specialists:
            problems.append(f"deliverable {d.get('id')}: assignee must be one of {sorted(specialists)}")
            continue
        assignees.add(d["assignee"])
        why = _show_problem(cfg, d["assignee"], show) or _route_ok(cfg, d["assignee"], d.get("task_type"), owner_text, brand_kit)
        if why:
            problems.append(f"deliverable {d.get('id')}: {why}")
    if c.get("size") in SIZE_LIMIT and len(assignees) > SIZE_LIMIT[c["size"]]:
        problems.append(f"size {c['size']} allows at most {SIZE_LIMIT[c['size']]} specialist(s) — raise the size (C5)")
    if c.get("size") == "S" and any(TIER.get(x, 0) >= 2 for x in c.get("planned_actions_tiers", []) or []):
        problems.append("S tasks can't include external (R2/R3) actions")
    return problems


def validate_plan(cfg: Config, lead: Employee, task_id: str, contract: dict, version: int, size: str,
                  handoffs: list[dict], owner_text: str, brand_kit: bool,
                  show: str | None = None) -> tuple[list[dict], list[str]]:
    problems, packets = [], []
    specialists = {s.id for s in cfg.specialists_of(lead.dept or "")}
    crit = {c["id"]: c for c in contract.get("acceptance_criteria", [])}
    deliverables = {d.get("id"): d for d in contract.get("deliverables", []) if isinstance(d, dict)}
    inherited = bool(contract.get("_inherited"))
    dept_refs = set(contract.get("_dept_inputs") or [])
    dept_authors = contract.get("_dept_input_authors") or {}   # X-artifact ref -> employee who made it
    covered: set[str] = set()
    if not handoffs:
        problems.append("no handoffs")
    if len(handoffs) > SIZE_LIMIT.get(size, 20):
        problems.append(f"size {size} allows at most {SIZE_LIMIT.get(size)} handoff(s) (C5)")
    for i, h in enumerate(handoffs, 1):
        to, tt = h.get("to"), h.get("task_type")
        if to not in specialists:
            problems.append(f"#{i}: '{to}' is not one of your specialists {sorted(specialists)}")
            continue
        if not inherited:  # C6: plan must match what the owner approved at G1
            dl = deliverables.get(h.get("deliverable"))
            if dl is None:
                problems.append(f"#{i}: deliverable must be one of {sorted(deliverables)}")
            elif dl.get("assignee") != to or dl.get("task_type") != tt:
                problems.append(f"#{i}: deliverable {h.get('deliverable')} was approved for {dl.get('assignee')}/"
                                f"{dl.get('task_type')}, not {to}/{tt}")
        why = _show_problem(cfg, to, show) or _route_ok(cfg, to, tt, owner_text, brand_kit, bool(h.get("skill_required")))
        if why:
            problems.append(f"#{i}: {why}")
        route = cfg.routes(to).get(tt or "")
        if route and route.upstream_from:
            authors = {handoffs[int(str(x)[1:]) - 1].get("to") for x in h.get("inputs_from") or []
                       if re.fullmatch(r"T\d+", str(x)) and 0 < int(str(x)[1:]) < i}
            authors |= {dept_authors.get(x) for x in h.get("inputs") or []}
            if not authors & set(route.upstream_from):
                problems.append(f"#{i}: {to}/{tt} works only from an output made by {list(route.upstream_from)} "
                                "(research brief or script) — give it inputs_from that packet, or ask the other "
                                "department via cross_dept")
        bad = [c for c in h.get("criteria", []) if c not in crit]
        if bad or not h.get("criteria"):
            problems.append(f"#{i}: criteria must be non-empty ids from the contract (bad: {bad})")
        covered |= set(h.get("criteria", []))
        for dep in h.get("inputs_from") or []:
            if not re.fullmatch(r"T\d+", str(dep)) or int(str(dep)[1:]) >= i:
                problems.append(f"#{i}: inputs_from may only name earlier packets (T1..T{i - 1}), got {dep}")
        bad_in = [x for x in h.get("inputs", []) if x not in dept_refs]
        if bad_in:
            problems.append(f"#{i}: explicit inputs must be other-department artifacts {sorted(dept_refs)}; use inputs_from for earlier packets")
        if len(str(h.get("context_summary", ""))) > 6000:
            problems.append(f"#{i}: context_summary too long")
        packets.append({"task_id": task_id, "contract_version": version, "from": lead.id, "to": to, "task_type": tt,
                        "deliverable": h.get("deliverable"), "objective": h.get("objective", ""),
                        "criteria": h.get("criteria", []), "inputs": h.get("inputs", []),
                        "inputs_from": h.get("inputs_from", []), "constraints": h.get("constraints", []),
                        "do_not": h.get("do_not", []), "context_summary": h.get("context_summary", ""),
                        "platform": h.get("platform"),
                        "spec": h.get("spec") or {}, "skill_required": bool(h.get("skill_required"))})
    needed = {cid for cid, c in crit.items() if c.get("check") != "owner_taste"}
    if needed - covered:
        problems.append(f"criteria not assigned to anyone: {sorted(needed - covered)} (C4)")
    return packets, problems


def validate_pending_actions(cfg: Config, emp: Employee, actions: list, approved_tiers: set[str] | None = None) -> list[str]:
    """C14: only R2/R3 actions this employee is allowed to prepare. C28: and only tiers the owner saw at G1."""
    bad = []
    for pa in actions:
        if not isinstance(pa, dict) or not pa.get("action"):
            bad.append("each pending action needs {action, params, preview}")
            continue
        a = str(pa["action"])
        tier = cfg.action_tier(a)
        if tier is None or tier == "R4":
            bad.append(f"{a}: not a permitted action")
        elif a not in emp.tools:
            bad.append(f"{a}: not in your allowlist")
        elif TIER[tier] < 2:
            bad.append(f"{a}: is {tier} — do it yourself with `act`, don't queue it for approval")
        elif not pa.get("preview"):
            bad.append(f"{a}: needs an exact preview for the owner")
        elif approved_tiers is not None and tier not in approved_tiers:
            bad.append(f"{a}: {tier} actions weren't in the approved contract — ask the owner via open_questions (C28)")
    return bad
