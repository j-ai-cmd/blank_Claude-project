"""The Dispatcher: deterministic code that runs the workforce (DESIGN-MAP §4–§10, §20).

Owner message -> Lead drafts contract (G1) -> Lead plans handoffs -> agent-harness loop runs each
specialist and verifies with machine checks -> LLM Verifier when §7 requires -> Lead delivery note ->
owner accepts (G4, memory ticks) -> R2/R3 actions as hash-bound G3 approvals.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import states
from .agents import AgentRunner, RunResult, ToolSpec, err, ok
from .config import TIER, Config, Employee
from .db import Approval, AuditEvent, MemoryEntry, Task
from .harness import Harness, HarnessError, plan_task_dir, task_dir
from .live import OWNER, LiveBus
from .memory import MemoryStore
from .pii import find_pii
from .policy import ALLOW, APPROVAL, Policy, action_hash
from .prompts import system_prompt, untrusted
from .routing import RouteError, resolve
from .slack import InboundMessage, SlackClient, approval_blocks

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
BUILTINS = {"WebSearch": "web.search", "WebFetch": "web.fetch"}
CRITERION_CHECKS = {"automatic", "verifier", "owner_taste"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


class Dispatcher:
    def __init__(self, cfg: Config, sessionmaker, runner: AgentRunner, slack: SlackClient | None = None,
                 harness: Harness | None = None):
        self.cfg = cfg
        self.Session = sessionmaker
        self.runner = runner
        self.slack = slack or SlackClient()
        self.policy = Policy(cfg)
        self.memory = MemoryStore(cfg)
        self.harness = harness or Harness(cfg)
        self.brand_kit = (cfg.dir.parent / "company" / "brand-kit.json").exists()
        b = cfg.permissions["budgets_default"]
        self.task_caps = b["cost_usd_per_task"]
        self.monthly_budget = float(b.get("monthly_llm_budget_usd", 20))
        self.live = LiveBus(list(cfg.employees), owner_of=self.task_owner)
        sessionmaker.configure(info={"live": self.live})
        self._seed_live()

    # ================================================================== live office
    def task_owner(self, dept: str) -> str | None:
        """The employee who owns a department's tasks (drafts, plans, delivers)."""
        return "chief_of_staff" if dept == "hq" else self.cfg.leads.get(dept)

    def _seed_live(self) -> None:
        """After a restart: rebuild presence from open tasks and pending approvals (no events emitted)."""
        with self.Session() as db:
            for t in db.scalars(select(Task).where(Task.status.notin_(list(states.TERMINAL)))):
                owner = self.task_owner(t.department)
                if owner:
                    self.live.seed_task(t.id, owner, t.status)
            for a in db.scalars(select(Approval).where(Approval.status == "pending")):
                t = db.get(Task, a.task_id)
                emp = (a.preview or {}).get("employee") or self.task_owner(t.department)
                self.live.seed_approval(a.id, a.task_id, emp)
            self._sync_paused(db)

    def _sync_paused(self, db: Session) -> None:
        self.live.set_paused({e.id for e in self.cfg.employees.values() if self.policy.paused(db, e)})

    def open_office_task(self, employee_id: str, text: str) -> str:
        """Owner clicked a desk (Chief of Staff or a Lead) and typed a request. Mirrors it to Slack."""
        emp = self.cfg.employee(employee_id)
        if emp.kind not in ("lead", "router"):
            raise ValueError("only the Chief of Staff and department Leads take requests")
        dept = emp.dept or "hq"
        try:
            channel = self.slack.resolve_channel_id(emp.channel) if emp.channel else self.cfg.owner_id
            opener = self.slack.post(channel, f"📋 From the office, for {emp.name}: {text}")
            thread = opener.get("ts")
        except Exception as e:  # Slack outage must not block the office
            print(f"[workforce] slack mirror failed: {e}")
            channel, thread = self.cfg.owner_id, None
        return self.create_task(dept, self.cfg.owner_id, text, channel, thread)

    # ================================================================== inbound
    async def handle_message(self, msg: InboundMessage) -> str:
        with self.Session() as db:
            if db.scalar(select(AuditEvent).where(AuditEvent.kind == "slack_event",
                                                  AuditEvent.detail["id"].as_string() == str(msg.event_id))):
                return "duplicate"
            db.add(AuditEvent(actor=msg.user, kind="slack_event", detail={"id": str(msg.event_id)}))
            db.commit()
        name = msg.channel_name or self.slack.channel_name(msg.channel) or msg.channel
        dept = self.cfg.dept_channels.get(name)
        if dept is None and not (msg.is_dm or name == self.cfg.org["core"]["chief_of_staff"]["channel"]):
            return "ignored-channel"
        if not self.policy.is_requester(msg.user, dept):
            self.slack.post(msg.channel, "Sorry — only the owner can give tasks here.", msg.thread_ts or msg.ts)
            self.slack.post(self.cfg.owner_id, f"Refused a request from <@{msg.user}> in {name}.")
            return "refused"
        if msg.thread_ts:
            with self.Session() as db:
                existing = db.scalar(select(Task.id).where(Task.slack_thread == msg.thread_ts,
                                                           Task.parent_id.is_(None)))
            if existing:
                await self.steer(existing, msg.user, msg.text)
                return "steered"
        tid = await self.start_task(dept or "hq", msg.user, msg.text, msg.channel, msg.ts)
        return tid

    def create_task(self, dept: str, user: str, text: str, channel: str, thread_ts: str | None,
                    parent_id: str | None = None) -> str:
        with self.Session() as db:
            t = Task(id=_id("task"), parent_id=parent_id, department=dept, requested_by=user,
                     original_request=text, slack_channel=channel, slack_thread=thread_ts,
                     contains_pii=bool(find_pii(text)))
            db.add(t)
            db.commit()
            tid = t.id
        to = self.task_owner(dept)
        self.live.task_created(tid, dept, to, text, parent_id)
        self.live.handoff(tid, "chief_of_staff" if parent_id else OWNER, to, "subtask" if parent_id else "request", text)
        return tid

    async def start_task(self, dept: str, user: str, text: str, channel: str, thread_ts: str,
                         parent_id: str | None = None, inherited_contract: dict | None = None) -> str:
        tid = self.create_task(dept, user, text, channel, thread_ts, parent_id)
        if inherited_contract is not None:
            await self._adopt_inherited_contract(tid, inherited_contract)
        else:
            await self.draft_contract(tid)
        return tid

    async def steer(self, task_id: str, user: str, text: str) -> None:
        """Owner replies in a task thread: one-off instruction -> new contract version, back to G1."""
        with self.Session() as db:
            t = db.get(Task, task_id)
            if t.status in states.TERMINAL:
                self._post(t, None, "This task is closed — start a new message for new work.")
                return
            notes = list((t.contract or {}).get("_owner_notes", [])) + [text]
            c = dict(t.contract or {})
            c["_owner_notes"] = notes
            t.contract = c
            if t.status not in ("RECEIVED", "CONTRACT_DRAFTED"):
                if "CONTRACT_DRAFTED" in states.ALLOWED.get(t.status, set()):
                    states.transition(db, t, "CONTRACT_DRAFTED", user, "owner changed direction")
                else:
                    db.commit()
                    self._post(t, None, f"Noted. I can't change direction while the task is {t.status}; "
                                        "I'll apply it at the next step.")
                    return
            db.commit()
        await self.draft_contract(task_id)

    # ================================================================== contract (G1)
    def _drafter(self, task: Task) -> Employee:
        if task.department == "hq":
            return self.cfg.employee("chief_of_staff")
        return self.cfg.employee(self.cfg.leads[task.department])

    async def draft_contract(self, task_id: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            emp = self._drafter(t)
            prompt = untrusted("owner_request", t.id, t.original_request)
            if (t.contract or {}).get("_owner_notes"):
                prompt += "\n\nOwner follow-ups (latest wins):\n" + "\n".join(
                    untrusted("owner_note", f"{t.id}-{i}", n) for i, n in enumerate(t.contract["_owner_notes"]))
            mem = self.memory.read(db, emp, t.original_request)
            system = system_prompt(self.cfg, emp, "contract", None, mem)
            db.commit()
        sink: dict = {}
        res = await self._run(emp, task_id, "contract", system, prompt, [self._submit_contract_tool(emp, sink)])
        with self.Session() as db:
            t = db.get(Task, task_id)
            if "contract" not in sink:
                self._post(t, emp, f"I couldn't draft a contract ({(res.errors or [res.text])[0] if (res.errors or res.text) else 'no output'}). "
                                   "Please rephrase or add detail.")
                db.commit()
                return
            c = sink["contract"]
            c["_owner_notes"] = (t.contract or {}).get("_owner_notes", [])
            states.new_contract_version(db, t, c, emp.id)
            t.size = c["size"]
            if t.status == "RECEIVED":
                states.transition(db, t, "CONTRACT_DRAFTED", emp.id)
            elif t.status != "CONTRACT_DRAFTED":
                states.transition(db, t, "CONTRACT_DRAFTED", emp.id)
            auto = (c["size"] == "S" and not c.get("questions")
                    and not any(TIER.get(x, 0) >= 2 for x in c.get("planned_actions_tiers", [])))
            body = self._contract_text(c)
            if auto:
                t.g1_approval_id = f"auto-S-{t.id}-v{t.contract_version}"
                states.transition(db, t, "CONTRACT_APPROVED", "policy", "S task auto-start")
                db.commit()
                self._post(t, emp, "*Contract (small task — starting now)*\n" + body)
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

    def _submit_contract_tool(self, emp: Employee, sink: dict) -> ToolSpec:
        schema = {"type": "object", "properties": {
            "objective": {"type": "string"}, "deliverables": {"type": "array", "items": {"type": "object"}},
            "acceptance_criteria": {"type": "array", "items": {"type": "object"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "out_of_scope": {"type": "array", "items": {"type": "string"}},
            "deadline": {"type": "string"}, "size": {"type": "string", "enum": ["S", "M", "L"]},
            "planned_actions_tiers": {"type": "array", "items": {"type": "string"}},
            "one_off_instructions": {"type": "array", "items": {"type": "string"}},
            "questions": {"type": "array", "items": {"type": "string"}},
            "departments": {"type": "array", "items": {"type": "object"}},
        }, "required": ["objective", "deliverables", "acceptance_criteria", "size"]}

        async def handler(args: dict) -> dict:
            problems = validate_contract(args, emp.kind == "router", self.cfg)
            if problems:
                return err("Contract rejected: " + "; ".join(problems) + ". Fix and call submit_contract again.")
            sink["contract"] = args
            return ok("Contract stored. Stop here.")
        return ToolSpec("submit_contract", "Submit the Task Contract (once).", schema, handler)

    async def _adopt_inherited_contract(self, task_id: str, contract: dict) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.new_contract_version(db, t, contract, "chief_of_staff")
            t.size = contract.get("size", "M")
            states.transition(db, t, "CONTRACT_DRAFTED", "chief_of_staff")
            t.g1_approval_id = f"inherited-{t.parent_id}"
            states.transition(db, t, "CONTRACT_APPROVED", "policy", "inherits parent G1 (internal sub-task)")
            db.commit()
        await self.plan(task_id)

    @staticmethod
    def _contract_text(c: dict) -> str:
        crit = "\n".join(f"{x['id']}. {x['text']} _({x.get('check', 'verifier')})_" for x in c["acceptance_criteria"])
        dels = "\n".join(f"• {d.get('description', d)}" for d in c["deliverables"])
        q = ("\n*Questions for you:*\n" + "\n".join(f"• {x}" for x in c["questions"])) if c.get("questions") else ""
        return (f"*Objective:* {c['objective']}\n*Deliverables:*\n{dels}\n*Acceptance criteria:*\n{crit}\n"
                f"*Size:* {c['size']}  *Deadline:* {c.get('deadline') or '-'}{q}")

    # ================================================================== approvals (G1/G2/G3/G4)
    async def on_approval(self, user: str, approval_id: str, approve: bool, button_hash: str | None = None,
                          memory_ticks: list[str] | None = None, reason: str = "") -> str:
        with self.Session() as db:
            a = db.get(Approval, approval_id)
            if a is None or a.status != "pending":
                return "stale"
            t = db.get(Task, a.task_id)
            if a.contract_version != t.contract_version:
                a.status = "expired"
                db.commit()
                return "stale"
            if a.gate == "G3" and button_hash != a.action_hash:
                return "hash-mismatch"
            tier = a.tier or ("R3" if a.gate in ("G1", "G4") else "R2")
            if not self.policy.can_approve(user, tier, t.department):
                db.add(AuditEvent(task_id=t.id, actor=user, kind="approval_denied", detail={"approval": a.id}))
                db.commit()
                return "not-an-approver"
            a.status = "approved" if approve else "rejected"
            a.decided_by, a.decided_at = user, datetime.now(timezone.utc)
            db.add(AuditEvent(task_id=t.id, actor=user, kind=f"{a.gate}_{a.status}", detail={"approval": a.id}))
            gate, tid = a.gate, t.id
            self.live.approval_closed(a.id, a.status)
            back_to = (a.preview or {}).get("employee") if gate == "G3" else self.task_owner(t.department)
            if back_to and not (gate == "G4" and approve):
                self.live.handoff(tid, OWNER, back_to, "approved" if approve else "rejected", reason, gate=gate)
            if gate == "G1":
                if approve:
                    t.g1_approval_id = a.id
                    states.transition(db, t, "CONTRACT_APPROVED", user)
                else:
                    states.transition(db, t, "CANCELLED", user, "owner cancelled at G1")
            db.commit()
        if gate == "G1" and approve:
            await self.plan(tid)
        elif gate == "G2":
            await (self.execute(tid) if approve else self._cancel(tid, user, "plan rejected"))
        elif gate == "G4":
            await (self.accept(tid, user, memory_ticks or []) if approve else self.reject(tid, user, reason))
        elif gate == "G3" and approve:
            await self.run_approved_action(approval_id)
        return "ok"

    async def _cancel(self, task_id: str, user: str, why: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.transition(db, t, "CANCELLED", user, why)
            db.commit()

    # ================================================================== plan
    async def plan(self, task_id: str, revision_notes: str = "") -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            if t.department == "hq":
                db.commit()
                await self._spawn_children(task_id)
                return
            emp = self.cfg.employee(self.cfg.leads[t.department])
            contract = {k: v for k, v in t.contract.items() if not k.startswith("_")}
            prompt = "Approved contract:\n" + json.dumps(contract, indent=1)
            if t.contract.get("_owner_notes"):
                prompt += "\nOwner notes:\n" + "\n".join(untrusted("owner_note", str(i), n) for i, n in enumerate(t.contract["_owner_notes"]))
            if revision_notes:
                prompt += "\n\nREVISION — fix these problems with a changed approach:\n" + revision_notes
            system = system_prompt(self.cfg, emp, "plan", None, self.memory.read(db, emp, t.original_request))
            db.commit()
        sink: dict = {}
        await self._run(emp, task_id, "plan", system, prompt, [self._submit_plan_tool(emp, task_id, sink)])
        with self.Session() as db:
            t = db.get(Task, task_id)
            if "plan" not in sink:
                states.transition(db, t, "ESCALATED" if t.status != "CONTRACT_APPROVED" else "CANCELLED", emp.id,
                                  "lead produced no valid plan")
                db.commit()
                self._post(t, emp, "I couldn't produce a valid plan — escalating to you.")
                return
            t.plan = sink["plan"]
            if t.status == "CONTRACT_APPROVED":
                states.transition(db, t, "PLANNED", emp.id)
            needs_g2 = t.size == "L" and not revision_notes
            if needs_g2:
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
        schema = {"type": "object", "properties": {"handoffs": {"type": "array", "items": {"type": "object"}}},
                  "required": ["handoffs"]}

        async def handler(args: dict) -> dict:
            with self.Session() as db:
                t = db.get(Task, task_id)
                crit_ids = {c["id"] for c in t.contract["acceptance_criteria"]}
                version = t.contract_version
            specialists = {s.id for s in self.cfg.specialists_of(lead.dept or "")}
            problems, packets = [], []
            for i, h in enumerate(args.get("handoffs") or [], 1):
                to = h.get("to")
                if to not in specialists:
                    problems.append(f"#{i}: '{to}' is not one of your specialists {sorted(specialists)}")
                    continue
                try:
                    resolve(self.cfg, to, h.get("task_type"), h.get("style_tags"), bool(h.get("skill_required")),
                            self.brand_kit)
                except RouteError as e:
                    problems.append(f"#{i}: {e}")
                bad = [c for c in h.get("criteria", []) if c not in crit_ids]
                if bad or not h.get("criteria"):
                    problems.append(f"#{i}: criteria must be non-empty ids from the contract (bad: {bad})")
                bad_in = [x for x in h.get("inputs", []) if not re.match(r"^(artifact|drive|crm|ats|pm|url|memory)://", str(x))]
                if bad_in:
                    problems.append(f"#{i}: inputs must be references, got {bad_in}")
                if len(str(h.get("context_summary", ""))) > 6000:
                    problems.append(f"#{i}: context_summary too long")
                packets.append({"task_id": task_id, "contract_version": version, "from": lead.id, "to": to,
                                "task_type": h.get("task_type"), "objective": h.get("objective", ""),
                                "criteria": h.get("criteria", []), "inputs": h.get("inputs", []),
                                "constraints": h.get("constraints", []), "do_not": h.get("do_not", []),
                                "context_summary": h.get("context_summary", ""), "style_tags": h.get("style_tags", []),
                                "platform": h.get("platform"), "spec": h.get("spec") or {},
                                "skill_required": bool(h.get("skill_required"))})
            if not packets and not problems:
                problems.append("no handoffs")
            if len(packets) > 20:
                problems.append("too many handoffs")
            if problems:
                return err("Plan rejected: " + "; ".join(problems))
            sink["plan"] = packets
            return ok(f"Plan stored ({len(packets)} handoffs). Stop here.")
        return ToolSpec("submit_plan", "Submit handoff packets (the harness plan).", schema, handler)

    async def _spawn_children(self, task_id: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            children = t.contract.get("departments") or []
            states.transition(db, t, "PLANNED", "chief_of_staff")
            states.transition(db, t, "IN_PROGRESS", "chief_of_staff", "sub-tasks spawned")
            db.commit()
            parent = {"id": t.id, "channel": t.slack_channel, "thread": t.slack_thread, "user": t.requested_by}
        for ch in children:
            sub = {"objective": ch["objective"], "deliverables": ch.get("deliverables") or [{"id": "D1", "description": ch["objective"], "format": "doc"}],
                   "acceptance_criteria": ch["acceptance_criteria"], "size": ch.get("size", "M"),
                   "planned_actions_tiers": ch.get("planned_actions_tiers", [])}
            internal = all(TIER.get(x, 0) <= 1 for x in sub["planned_actions_tiers"])
            if internal:
                await self.start_task(ch["department"], parent["user"], ch["objective"], parent["channel"],
                                      parent["thread"], parent_id=parent["id"], inherited_contract=sub)
            else:
                await self.start_task(ch["department"], parent["user"], ch["objective"], parent["channel"],
                                      parent["thread"], parent_id=parent["id"])

    # ================================================================== execute (agent-harness)
    async def execute(self, task_id: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            if t.status == "PLANNED":
                states.transition(db, t, "IN_PROGRESS", "dispatcher")
            elif t.status == "REVISION":
                states.transition(db, t, "IN_PROGRESS", "dispatcher", "revision round")
            route_checks, resolved = {}, {}
            for i, h in enumerate(t.plan, 1):
                r = resolve(self.cfg, h["to"], h["task_type"], h.get("style_tags"), h.get("skill_required", False), self.brand_kit)
                route_checks[f"T{i}"] = r.checks
                resolved[f"T{i}"] = r
            plan = self.harness.build_plan(t.id, t.contract["objective"], t.department, t.plan, route_checks)
            db.commit()
            plan_packets = list(t.plan)
        # fresh harness state per round
        shutil.rmtree(task_dir(task_id) / "T1", ignore_errors=True)
        for i in range(2, len(plan_packets) + 1):
            shutil.rmtree(task_dir(task_id) / f"T{i}", ignore_errors=True)
        (task_dir(task_id) / "artifacts").mkdir(parents=True, exist_ok=True)
        if not (task_dir(task_id) / "fetch_log.json").exists():
            (task_dir(task_id) / "fetch_log.json").write_text("[]")
        self.harness.init(task_id, plan)
        failures: dict[str, list[str]] = {}
        while True:
            d = self.harness.next(task_id)
            if d.action == "execute":
                pt = d.task
                idx = int(pt[1:]) - 1
                h = plan_packets[idx]
                attempt = len(failures.get(pt, [])) + 1
                self.live.handoff(task_id, h["from"], h["to"], "assign", h["objective"], step=pt, attempt=attempt,
                                  task_type=h["task_type"])
                ok_run = await self._run_specialist(task_id, pt, h, resolved[pt], failures.get(pt, []))
                self.harness.record_execute(task_id, pt, ok_run)
                passed = False
                if ok_run:
                    result, _ = self.harness.verify(task_id, pt)
                    passed = result.get("status") == "verified"
                    if not passed:
                        failed = [{"cmd": f["cmd"].split(" ")[3] if f["cmd"].startswith("python3 -m") else f["cmd"],
                                   "output": f.get("tail")} for f in result.get("failed_checks", [])]
                        failures.setdefault(pt, []).append(json.dumps(failed or result)[:1500])
                else:
                    failures.setdefault(pt, []).append("You did not call submit_return with a valid return packet.")
                rp_path = plan_task_dir(task_id, pt) / "return.json"
                summary = json.loads(rp_path.read_text()).get("summary", "") if ok_run and rp_path.exists() else ""
                self.live.handoff(task_id, h["to"], h["from"], "return", summary, step=pt, attempt=attempt,
                                  checks_passed=passed)
                if await self._budget_exceeded(task_id):
                    return
                continue
            if d.action == "verify":
                self.harness.verify(task_id, d.task)
                continue
            if d.action == "close":
                closed, code = self.harness.close(task_id)
                if code != 0:
                    raise HarnessError(f"close refused: {closed}")
                break
            # escalate (attempts or iterations exhausted) or anything unexpected
            with self.Session() as db:
                t = db.get(Task, task_id)
                states.transition(db, t, "ESCALATED", "harness", json.dumps(d.detail)[:500])
                db.commit()
                self._post(t, None, f"⚠️ Escalated: {d.detail.get('detail', d.action)}. Evidence log is in the task workspace. "
                                    "Reply in this thread to change direction.")
            return
        await self.verify(task_id)

    async def _run_specialist(self, task_id: str, pt: str, handoff: dict, route, failures: list[str]) -> bool:
        emp = self.cfg.employee(handoff["to"])
        d = plan_task_dir(task_id, pt)
        (d / "artifacts").mkdir(parents=True, exist_ok=True)
        (d / "handoff.json").write_text(json.dumps(handoff, indent=2))
        (d / "spec.json").write_text(json.dumps(handoff.get("spec") or {}))
        with self.Session() as db:
            mem = self.memory.read(db, emp, handoff["objective"])
            db.commit()
        system = system_prompt(self.cfg, emp, "execute", route, mem)
        prompt = "Handoff packet:\n" + json.dumps({k: v for k, v in handoff.items() if k != "task_id"}, indent=1)
        if failures:
            prompt += "\n\nPrevious attempt failed these checks — change your approach:\n" + "\n".join(failures[-2:])
        sink: dict = {}
        tools = self._common_tools(emp, task_id, pt, allowed_inputs=set(handoff.get("inputs", [])))
        tools.append(self._submit_return_tool(emp, task_id, pt, handoff, sink))
        tools.append(self._act_tool(emp, task_id))
        await self._run(emp, task_id, "execute", system, prompt, tools)
        rp = sink.get("return")
        if not rp or rp.get("status") not in ("done", "partial"):
            return False
        (d / "return.json").write_text(json.dumps(rp, indent=2))
        outs = [o.split("/")[-1] for o in rp.get("outputs", [])]
        for name in outs:
            src = task_dir(task_id) / "artifacts" / name
            if src.exists():
                shutil.copy(src, d / "artifacts" / name)
        if outs and (task_dir(task_id) / "artifacts" / outs[0]).exists():
            shutil.copy(task_dir(task_id) / "artifacts" / outs[0], d / "primary")
        return True

    # ------------------------------------------------------------------ tools given to agents
    def _check(self, emp: Employee, task_id: str, action: str, params: dict | None = None):
        with self.Session() as db:
            t = db.get(Task, task_id)
            dec = self.policy.check(db, emp, action, params or {}, t)
            db.commit()
        return dec

    def _common_tools(self, emp: Employee, task_id: str, pt: str | None, allowed_inputs: set[str] | None = None) -> list[ToolSpec]:
        art = task_dir(task_id) / "artifacts"
        art.mkdir(parents=True, exist_ok=True)
        tools: list[ToolSpec] = []
        own: set[str] = set()

        async def ws_write(args):
            dec = self._check(emp, task_id, "workspace.write", {"name": args.get("name")})
            if not dec.allowed:
                return err(dec.reason)
            name = SAFE_NAME.sub("_", str(args["name"]))[:100]
            (art / name).write_text(str(args["content"]))
            own.add(name)
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="artifact", detail={"name": name, "pt": pt}))
                db.commit()
            self.live.publish("artifact.created", task_id, employee_id=emp.id, name=name, step=pt)
            return ok(f"saved artifact://{task_id}/{name}")

        async def ws_read(args):
            dec = self._check(emp, task_id, "workspace.read", {"ref": args.get("ref")})
            if not dec.allowed:
                return err(dec.reason)
            ref = str(args["ref"])
            name = SAFE_NAME.sub("_", ref.split("/")[-1])
            if allowed_inputs is not None and ref not in allowed_inputs and name not in own:
                return err("you may only read artifacts listed in your handoff inputs or ones you wrote")
            p = art / name
            if not p.exists():
                return err("no such artifact")
            return ok(untrusted("artifact", name, p.read_text(errors="replace")[:50_000]))

        async def mem_read(args):
            dec = self._check(emp, task_id, "memory.read_scoped", {})
            if not dec.allowed:
                return err(dec.reason)
            with self.Session() as db:
                rows = self.memory.read(db, emp, str(args.get("query", "")))
                db.commit()
                return ok("\n".join(f"[{m.id}] {m.content}" for m in rows) or "nothing relevant")

        async def slack_post(args):
            dec = self._check(emp, task_id, "slack.post_own_thread", {"text": str(args.get("text", ""))[:200]})
            if not dec.allowed:
                return err(dec.reason)
            with self.Session() as db:
                t = db.get(Task, task_id)
                self._post(t, emp, str(args["text"])[:3000])
            return ok("posted in the task thread")

        tools += [
            ToolSpec("workspace_write", "Save an output artifact (text) to the task workspace.",
                     {"type": "object", "properties": {"name": {"type": "string"}, "content": {"type": "string"}}, "required": ["name", "content"]}, ws_write),
            ToolSpec("workspace_read", "Read an artifact by artifact:// ref (only refs in your inputs, or your own).",
                     {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}, ws_read),
            ToolSpec("memory_read", "Search your permitted memory.",
                     {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, mem_read),
        ]
        if "slack.post_own_thread" in emp.tools:
            tools.append(ToolSpec("slack_post", "Post a short progress note in the task thread.",
                                  {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, slack_post))
        return tools

    def _act_tool(self, emp: Employee, task_id: str) -> ToolSpec:
        """Generic connector action. R2/R3 never execute here: they must go in pending_actions."""
        async def act(args):
            action, params = str(args.get("action")), dict(args.get("params") or {})
            dec = self._check(emp, task_id, action, params)
            if dec.outcome == APPROVAL:
                return err(f"'{action}' needs owner approval ({dec.tier}: {dec.reason}). Don't retry — add it to "
                           "pending_actions in your return packet with an exact preview.")
            if not dec.allowed:
                return err(f"denied: {dec.reason}")
            return err(f"'{action}' is permitted but no connector is configured for it yet. Say so in open_questions.")
        return ToolSpec("act", "Use a business tool from your allowlist, e.g. {action:'crm.read', params:{...}}.",
                        {"type": "object", "properties": {"action": {"type": "string"}, "params": {"type": "object"}},
                         "required": ["action"]}, act)

    def _submit_return_tool(self, emp: Employee, task_id: str, pt: str, handoff: dict, sink: dict) -> ToolSpec:
        async def handler(args):
            rp = {"task_id": task_id, "from": emp.id, **args}
            rp.setdefault("self_check", [])
            rp.setdefault("confidence", 0.5)
            rp.setdefault("outputs", [])
            missing = [o for o in rp["outputs"] if not (task_dir(task_id) / "artifacts" / o.split("/")[-1]).exists()]
            if missing:
                return err(f"outputs not found in workspace (write them first): {missing}")
            if not all(str(o).startswith("artifact://") for o in rp["outputs"]):
                return err("outputs must be artifact:// refs")
            with self.Session() as db:
                t = db.get(Task, task_id)
                for mc in rp.get("memory_candidates") or []:
                    content = mc.get("content") if isinstance(mc, dict) else str(mc)
                    if content:
                        self.memory.submit_candidate(db, emp, t, content, kind=(mc.get("kind") if isinstance(mc, dict) else None) or "feedback",
                                                     layer=(mc.get("layer") if isinstance(mc, dict) else None) or "L3",
                                                     pointer=mc.get("pointer") if isinstance(mc, dict) else None,
                                                     derived_from_untrusted=bool(rp.get("citations")))
                db.commit()
            rp["memory_candidates"] = []  # stored separately (schema-typed rows)
            sink["return"] = rp
            return ok("Return packet stored. Stop here.")
        schema = {"type": "object", "properties": {
            "status": {"type": "string", "enum": ["done", "partial", "blocked", "out_of_scope"]},
            "outputs": {"type": "array", "items": {"type": "string"}}, "summary": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "object"}},
            "self_check": {"type": "array", "items": {"type": "object"}},
            "confidence": {"type": "number"}, "open_questions": {"type": "array", "items": {"type": "string"}},
            "pending_actions": {"type": "array", "items": {"type": "object"}},
            "memory_candidates": {"type": "array", "items": {"type": "object"}}},
            "required": ["status", "outputs", "self_check", "confidence"]}
        return ToolSpec("submit_return", "Submit your return packet (once).", schema, handler)

    # ================================================================== verify (LLM Verifier, §7)
    def _needs_llm_verifier(self, t: Task) -> bool:
        if t.size in ("M", "L"):
            return True
        if any(TIER.get(x, 0) >= 2 for x in t.contract.get("planned_actions_tiers", [])):
            return True
        for i in range(1, len(t.plan) + 1):
            p = plan_task_dir(t.id, f"T{i}") / "return.json"
            if p.exists() and json.loads(p.read_text()).get("citations"):
                return True
        return False

    async def verify(self, task_id: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.transition(db, t, "VERIFYING", "harness", "all plan tasks passed automatic checks")
            need = self._needs_llm_verifier(t)
            if not need:
                t.verification_id = f"auto-checks-{t.id}-v{t.contract_version}-r{t.revisions}"
            db.commit()
        if not need:
            await self.deliver(task_id)
            return
        vera = self.cfg.employee("verifier")
        with self.Session() as db:
            t = db.get(Task, task_id)
            contract = {k: v for k, v in t.contract.items() if not k.startswith("_")}
            db.commit()
        arts = []
        for p in sorted((task_dir(task_id) / "artifacts").glob("*")):
            arts.append(untrusted("deliverable", p.name, p.read_text(errors="replace")[:30_000]))
        cites = []
        for i in range(1, 30):
            rp = plan_task_dir(task_id, f"T{i}") / "return.json"
            if not rp.exists():
                break
            cites += json.loads(rp.read_text()).get("citations", [])
        prompt = ("Contract:\n" + json.dumps(contract, indent=1) + "\n\nDeliverables:\n" + "\n\n".join(arts) +
                  "\n\nCited sources (re-fetch URLs with WebFetch if you need to):\n" + json.dumps(cites, indent=1))
        sink: dict = {}

        async def submit_verdict(args):
            grades = args.get("grades") or []
            ids = {c["id"] for c in contract["acceptance_criteria"]}
            if {g.get("criterion_id") for g in grades} != ids:
                return err(f"grade every criterion exactly once: {sorted(ids)}")
            sink["verdict"] = args
            return ok("Verdict stored. Stop here.")
        tools = [ToolSpec("submit_verdict", "Submit criterion grades (once).",
                          {"type": "object", "properties": {"grades": {"type": "array", "items": {"type": "object"}},
                                                            "uncited_claims": {"type": "array", "items": {"type": "string"}}},
                           "required": ["grades"]}, submit_verdict)]
        owner = self.task_owner(self._dept(task_id))
        self.live.handoff(task_id, owner, vera.id, "for_verification", contract.get("objective", ""))
        await self._run(vera, task_id, "verify", system_prompt(self.cfg, vera, "verify"), prompt, tools)
        verdict = sink.get("verdict")
        if verdict:
            n_fail = sum(1 for g in verdict["grades"] if g.get("result") == "FAIL")
            self.live.handoff(task_id, vera.id, owner, "verdict", "PASS" if not n_fail else f"{n_fail} criteria failed",
                              passed=not n_fail and not verdict.get("uncited_claims"))
        with self.Session() as db:
            t = db.get(Task, task_id)
            if not verdict:
                states.transition(db, t, "ESCALATED", "verifier", "verifier produced no verdict")
                db.commit()
                self._post(t, vera, "⚠️ I couldn't complete verification — escalating.")
                return
            fails = [g for g in verdict["grades"] if g.get("result") == "FAIL"]
            c = dict(t.contract)
            c["_verification"] = verdict
            t.contract = c
            if fails or verdict.get("uncited_claims"):
                t.revisions += 1
                if t.revisions > int(self.cfg.permissions["budgets_default"]["revision_loops"]):
                    states.transition(db, t, "ESCALATED", "verifier", "revision limit reached")
                    db.commit()
                    self._post(t, vera, "⚠️ Still failing after 2 revisions — escalating to you.\n" + json.dumps(fails)[:1500])
                    return
                states.transition(db, t, "REVISION", "verifier")
                db.commit()
                notes = json.dumps({"failed": fails, "uncited_claims": verdict.get("uncited_claims", [])})[:3000]
            else:
                t.verification_id = f"ver_{uuid.uuid4().hex[:8]}"
                db.commit()
                notes = None
        if notes:
            await self.plan(task_id, revision_notes=notes)
            return
        await self.deliver(task_id)

    def _dept(self, task_id: str) -> str:
        with self.Session() as db:
            return db.get(Task, task_id).department

    # ================================================================== deliver (G4)
    async def deliver(self, task_id: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            lead = self.cfg.employee(self.cfg.leads[t.department]) if t.department in self.cfg.leads else self.cfg.employee("chief_of_staff")
            arts = sorted(p.name for p in (task_dir(task_id) / "artifacts").glob("*"))
            db.commit()
        sink: dict = {}

        async def submit_delivery(args):
            sink["note"] = str(args.get("note", ""))[:3000]
            return ok("Delivery stored. Stop here.")
        with self.Session() as db:
            report = (db.get(Task, task_id).contract or {}).get("_verification", "automatic checks only")
        prompt = f"Artifacts produced: {arts}\nVerifier report: {json.dumps(report)[:3000]}"
        await self._run(lead, task_id, "deliver", system_prompt(self.cfg, lead, "deliver"), prompt,
                        [ToolSpec("submit_delivery", "Submit the owner-facing delivery note (once).",
                                  {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}, submit_delivery)])
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.transition(db, t, "DELIVERED", lead.id)
            t.delivery = {"note": sink.get("note", "(no note)"), "artifacts": arts}
            cands = list(db.scalars(select(MemoryEntry).where(MemoryEntry.task_id == t.id, MemoryEntry.status == "candidate")))
            a = Approval(id=_id("apr"), task_id=t.id, gate="G4", contract_version=t.contract_version,
                         preview={"artifacts": arts})
            db.add(a)
            db.commit()
            body = (f"{t.delivery['note']}\n\n*Artifacts:* {', '.join(arts) or '-'}\n*Verification:* {t.verification_id}\n"
                    f"*Cost so far:* ${t.cost_usd:.2f}")
            ticks = [(m.id, ("⚠ " if m.derived_from_untrusted else "") + m.content) for m in cands]
            self._post(t, lead, "Delivered — please accept or reject", blocks=approval_blocks(
                "G4 · Accept delivery?", body, a.id, checkboxes=ticks or None))
            self.live.approval_requested(a.id, t.id, "G4", lead.id, "Accept delivery?", body)
            self.live.handoff(t.id, lead.id, OWNER, "delivery", t.delivery["note"], approval_id=a.id,
                              artifacts=arts, memory_candidates=[{"id": i, "text": x} for i, x in ticks])

    async def accept(self, task_id: str, user: str, ticks: list[str]) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.transition(db, t, "ACCEPTED", user)
            db.flush()
            for m in db.scalars(select(MemoryEntry).where(MemoryEntry.task_id == t.id, MemoryEntry.status == "candidate")):
                self.memory.promote(db, m.id, t, owner_ticked=m.id in ticks)
            pending = []
            for i in range(1, len(t.plan) + 1):
                rp = plan_task_dir(t.id, f"T{i}") / "return.json"
                if rp.exists():
                    for pa in json.loads(rp.read_text()).get("pending_actions") or []:
                        pending.append((t.plan[i - 1]["to"], pa))
            g3 = []
            for emp_id, pa in pending:
                action, params = str(pa.get("action")), dict(pa.get("params") or {})
                tier = self.cfg.action_tier(action) or "R4"
                if tier == "R4":
                    continue
                a = Approval(id=_id("apr"), task_id=t.id, gate="G3", tier=tier if TIER[tier] >= 2 else "R2",
                             action=action, action_hash=action_hash(action, params),
                             contract_version=t.contract_version,
                             preview={"employee": emp_id, "params": params, "preview": pa.get("preview")})
                db.add(a)
                g3.append(a)
            states.transition(db, t, "CLOSED", user)
            db.commit()
            parent = t.parent_id
            for a in g3:
                body = f"*{a.preview['employee']}* wants to run `{a.action}` ({a.tier})\n```{json.dumps(a.preview, indent=1)[:2500]}```"
                self._post(t, None, f"Approval needed: {a.action}", blocks=approval_blocks(
                    f"G3 · {a.action}", body, a.id, action_hash=a.action_hash))
                self.live.approval_requested(a.id, t.id, "G3", a.preview["employee"], a.action, body, a.action_hash)
                self.slack.post(self.slack.resolve_channel_id("#approvals"), f"G3 approval pending for task {t.id}: {a.action}")
        if parent:
            self.live.handoff(task_id, self.task_owner(t.department), "chief_of_staff", "subtask_done", t.department,
                              parent_id=parent)
            await self._child_finished(parent)

    async def reject(self, task_id: str, user: str, reason: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.transition(db, t, "REJECTED", user, reason)
            producers = {row.actor for row in db.scalars(select(AuditEvent).where(AuditEvent.task_id == t.id, AuditEvent.kind == "artifact"))}
            if reason:
                for pid in producers:
                    m = self.memory.submit_candidate(db, self.cfg.employee(pid), t, f"Owner rejected: {reason}", kind="feedback")
                    db.flush()
                    m.status = "active"  # direct owner feedback (memory.yaml: direct_owner_instruction)
                    m.verified_by = user
            states.transition(db, t, "REVISION", user)
            t.revisions = 0  # human rejection doesn't count toward the automatic revision limit (§5)
            db.commit()
        await self.plan(task_id, revision_notes=f"Owner rejected the delivery: {reason or '(no reason given)'}")

    async def _child_finished(self, parent_id: str) -> None:
        with self.Session() as db:
            p = db.get(Task, parent_id)
            kids = list(db.scalars(select(Task).where(Task.parent_id == parent_id)))
            if kids and all(k.status == "CLOSED" for k in kids) and p.status == "IN_PROGRESS":
                p.verification_id = f"children-{parent_id}"
                states.transition(db, p, "VERIFYING", "chief_of_staff")
                states.transition(db, p, "DELIVERED", "chief_of_staff")
                a = Approval(id=_id("apr"), task_id=p.id, gate="G4", contract_version=p.contract_version)
                db.add(a)
                db.commit()
                summary = "\n".join(f"• {k.department}: {k.status}" for k in kids)
                self._post(p, self.cfg.employee("chief_of_staff"), "All departments delivered",
                           blocks=approval_blocks("G4 · Close cross-department task?", summary, a.id))
                self.live.approval_requested(a.id, p.id, "G4", "chief_of_staff", "Close cross-department task?", summary)
                self.live.handoff(p.id, "chief_of_staff", OWNER, "delivery", summary, approval_id=a.id)

    # ================================================================== G3 execution
    async def run_approved_action(self, approval_id: str) -> None:
        with self.Session() as db:
            a = db.get(Approval, approval_id)
            t = db.get(Task, a.task_id)
            emp = self.cfg.employee(a.preview["employee"])
            params = dict(a.preview.get("params") or {})
            params["approval_id"] = a.id
            from .db import ActionRun
            if db.scalar(select(ActionRun).where(ActionRun.task_id == t.id, ActionRun.action_hash == a.action_hash)):
                return  # idempotent: never twice
            dec = self.policy.check(db, emp, a.action, params, t)
            if dec.outcome != ALLOW:
                db.commit()
                self._post(t, None, f"Approved action `{a.action}` was blocked: {dec.reason}")
                return
            db.add(ActionRun(task_id=t.id, action_hash=a.action_hash, status="failed",
                             result={"error": "no connector configured"}))
            db.commit()
            self._post(t, emp, f"`{a.action}` is approved, but no connector is configured for it yet — nothing was sent.")

    # ================================================================== runner + budgets
    async def _run(self, emp: Employee, task_id: str, phase: str, system: str, prompt: str,
                   tools: list[ToolSpec]) -> RunResult:
        with self.Session() as db:
            t = db.get(Task, task_id)
            if self.policy.paused(db, emp):
                return RunResult(is_error=True, text=self.policy.paused(db, emp) or "paused")
            cap = float(self.task_caps.get(t.size or "S", self.task_caps["S"]))
            remaining = max(0.0, cap - t.cost_usd)
            db.commit()
        if remaining <= 0:
            return RunResult(is_error=True, text="task budget exhausted")
        builtins = {name: action for name, action in BUILTINS.items() if action in emp.tools}

        async def gate(tool_name: str, tool_input: dict) -> tuple[bool, str]:
            action = builtins[tool_name]
            params = {"url": tool_input.get("url")} if action == "web.fetch" else {"query": tool_input.get("query")}
            dec = self._check(emp, task_id, action, params)
            if dec.allowed and action == "web.fetch":
                with self.Session() as db:
                    db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="fetched", detail={"url": params["url"]}))
                    db.commit()
                log = task_dir(task_id) / "fetch_log.json"
                urls = json.loads(log.read_text()) if log.exists() else []
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text(json.dumps(sorted(set(urls + [params["url"]]))))
            return dec.allowed, dec.reason

        self.live.run_started(emp.id, task_id, phase)
        try:
            res = await self.runner.run(employee_id=emp.id, model=emp.model, phase=phase, system=system, prompt=prompt,
                                        tools=tools, builtins=builtins, gate=gate, max_turns=30, budget_usd=remaining)
        except Exception as e:  # SDK/CLI failures must not crash the dispatcher
            res = RunResult(is_error=True, text=f"{type(e).__name__}: {e}")
        with self.Session() as db:
            t = db.get(Task, task_id)
            t.cost_usd += res.cost_usd
            spent = self.policy.bump(db, f"month:{_month()}", "plan", "llm_usd", res.cost_usd)
            db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="agent_run",
                              detail={"phase": phase, "cost": res.cost_usd, "error": res.is_error, "text": res.text[:300]}))
            if spent >= self.monthly_budget:
                self.policy.pause(db, "all", f"monthly plan credit (${self.monthly_budget:.0f}) used — resumes next month", "budget")
                self._sync_paused(db)
            db.commit()
            self.live.publish("cost", task_id, task_cost_usd=round(t.cost_usd, 4), month_spent_usd=round(spent, 4),
                              month_budget_usd=self.monthly_budget)
        self.live.run_finished(emp.id, task_id, phase, res.cost_usd, res.is_error)
        return res

    async def _budget_exceeded(self, task_id: str) -> bool:
        with self.Session() as db:
            t = db.get(Task, task_id)
            cap = float(self.task_caps.get(t.size or "S", self.task_caps["S"]))
            if t.cost_usd >= cap:
                states.transition(db, t, "ESCALATED", "budget", f"task budget ${cap} used")
                db.commit()
                self._post(t, None, f"⚠️ Task budget (${cap}) used up — escalating. Reply to continue or cancel.")
                return True
        return False

    # ================================================================== slack out
    def _post(self, t: Task, emp: Employee | None, text: str, blocks: list | None = None) -> None:
        persona = {"name": emp.name, "icon_emoji": ":robot_face:"} if emp else {"name": "Dispatcher", "icon_emoji": ":gear:"}
        self.live.said(t.id, emp.id if emp else None, text)
        try:
            self.slack.post(t.slack_channel or self.cfg.owner_id, text, t.slack_thread, persona, blocks)
        except Exception as e:  # Slack outage must not lose task state
            print(f"[workforce] slack post failed: {e}")

    # ================================================================== owner commands
    def command(self, user: str, text: str) -> str:
        if user != self.cfg.owner_id:
            return "Only the owner can run commands."
        parts = text.strip().split()
        if not parts:
            return "commands: pause-all | pause <emp|dept> | resume <all|emp|dept> | status | gc"
        cmd = parts[0].lstrip("/")
        with self.Session() as db:
            if cmd == "pause-all":
                self.policy.pause(db, "all", "owner kill switch", user)
                db.commit()
                self._sync_paused(db)
                return "All employees paused."
            if cmd == "pause" and len(parts) > 1:
                scope = f"dept:{parts[1]}" if parts[1] in self.cfg.org["departments"] else f"emp:{parts[1]}"
                self.policy.pause(db, scope, "owner", user)
                db.commit()
                self._sync_paused(db)
                return f"Paused {scope}."
            if cmd == "resume" and len(parts) > 1:
                scope = "all" if parts[1] == "all" else (f"dept:{parts[1]}" if parts[1] in self.cfg.org["departments"] else f"emp:{parts[1]}")
                self.policy.resume(db, scope, user)
                db.commit()
                self._sync_paused(db)
                return f"Resumed {scope}."
            if cmd == "status":
                rows = db.scalars(select(Task).where(Task.status.notin_(list(states.TERMINAL))).order_by(Task.created_at.desc()).limit(20))
                spent = self.policy.counter_value(db, f"month:{_month()}", "plan", "llm_usd")
                lines = [f"{r.id} {r.department} {r.status} ${r.cost_usd:.2f}" for r in rows]
                return f"Plan credit used this month: ${spent:.2f} / ${self.monthly_budget:.0f}\n" + ("\n".join(lines) or "no open tasks")
            if cmd == "gc":
                rep = self.memory.gc(db)
                db.commit()
                return f"Memory GC: {rep}"
        return "unknown command"


def validate_contract(c: dict, is_router: bool, cfg: Config) -> list[str]:
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
    if is_router:
        depts = c.get("departments") or []
        if not depts:
            problems.append("Chief of Staff contracts must list departments[] with per-department objective + acceptance_criteria")
        for d in depts:
            if d.get("department") not in cfg.org["departments"]:
                problems.append(f"unknown department {d.get('department')}")
            if not d.get("acceptance_criteria"):
                problems.append(f"{d.get('department')}: acceptance_criteria required")
    return problems
