"""The Dispatcher: deterministic code that runs the workforce (DESIGN-MAP §4–§10, §20).

Owner message -> Lead drafts contract with assignee + task_type per deliverable (G1) -> Lead plans
handoffs (must match the contract, cover every criterion, fit the size) -> agent-harness loop runs each
specialist, passing upstream outputs forward, and verifies with machine checks -> LLM Verifier when §7
requires (incl. any numbers/claims) -> Lead delivery note from real summaries -> owner accepts (G4,
memory ticks) -> R2/R3 actions as hash-bound G3 approvals (R3 double-confirm).

Every tool call from every agent goes through `_guard` -> Policy.check -> audit.

The class is split into mixins (contracts, toolbox, verification, delivery, routines); this file keeps intake, execution, `_run` and the budget."""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import states
from .agents import AgentRunner, RunResult, ToolSpec
from .config import Config, Employee
from .contracts import ContractsMixin, validate_contract, validate_pending_actions, validate_plan
from .db import Approval, AuditEvent, MemoryEntry, Task
from .delivery import DeliveryMixin
from .dispatch_common import BUILTINS, CHITCHAT, LOW_CONFIDENCE, RESUME_WORDS, STANDING, VERIFY, _id, _month, normalize_ids
from .harness import Harness, HarnessError, plan_task_dir, task_dir
from .live import LiveBus, OWNER
from .memory import MemoryStore
from .pii import find_pii
from .policy import Policy
from .prompts import owner_request, system_prompt, untrusted
from .routines import RoutinesMixin
from .routing import resolve
from .slack import InboundMessage, SlackClient, approval_blocks
from .toolbox import ToolboxMixin
from .verification import VerificationMixin


class Dispatcher(ContractsMixin, ToolboxMixin, VerificationMixin, DeliveryMixin, RoutinesMixin):
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
        self.revision_limit = int(b["revision_loops"])
        self._active: set[str] = set()   # task ids with a loop running in this process
        from .connectors import EmailReader
        self.email_reader = EmailReader()   # tests inject a fake
        self.max_open = int(b["concurrent_tasks_per_lead"])
        self.max_per_show = int(b.get("concurrent_tasks_per_show", 2))
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
            for a in db.scalars(select(Approval).where(Approval.status.in_(["pending", "confirming"]))):
                t = db.get(Task, a.task_id)
                emp = (a.preview or {}).get("employee") or self.task_owner(t.department)
                self.live.seed_approval(a.id, a.task_id, emp)
            self._sync_paused(db)

    def _sync_paused(self, db: Session) -> None:
        self.live.set_paused({e.id for e in self.cfg.employees.values() if self.policy.paused(db, e)})

    def office_target(self, employee_id: str) -> tuple[str, str, str | None]:
        """Owner clicked a desk (Chief of Staff or a Lead). Returns (dept, channel, thread) and mirrors to Slack."""
        emp = self.cfg.employee(employee_id)
        if emp.kind not in ("lead", "router"):
            raise ValueError("only the Chief of Staff and department Leads take requests")
        dept = emp.dept or "hq"
        try:
            channel = self.slack.resolve_channel_id(emp.channel) if emp.channel else self.cfg.owner_id
            return dept, channel, self.slack.post(channel, f"📋 From the office, for {emp.name}").get("ts")
        except Exception as e:  # Slack outage must not block the office
            print(f"[workforce] slack mirror failed: {e}")
            return dept, self.cfg.owner_id, None

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
        if not msg.thread_ts and is_chitchat(msg.text):
            self.slack.post(msg.channel, "👍 (no task created — send a request to start one)", msg.ts)
            return "chitchat"
        if msg.thread_ts:
            with self.Session() as db:
                existing = db.scalar(select(Task.id).where(Task.slack_thread == msg.thread_ts,
                                                           Task.parent_id.is_(None)))
            if existing:
                await self.steer(existing, msg.user, msg.text)
                return "steered"
        return await self.start_task(dept or "hq", msg.user, msg.text, msg.channel, msg.ts)

    async def start_task(self, dept: str, user: str, text: str, channel: str, thread_ts: str,
                         parent_id: str | None = None, inherited_contract: dict | None = None,
                         show: str | None = None, on_created=None) -> str:
        named = self.cfg.shows_named(text) if parent_id is None else []
        with self.Session() as db:
            t = Task(id=_id("task"), parent_id=parent_id, department=dept, requested_by=user,
                     original_request=text, slack_channel=channel, slack_thread=thread_ts,
                     contains_pii=bool(find_pii(text)),
                     show=show if parent_id else (named[0] if len(named) == 1 else None))   # children inherit (I1)
            if len(named) > 1:
                t.contract = {"_show_question": named}
            db.add(t)
            db.commit()
            tid = t.id
        to = self.task_owner(dept)
        self.live.task_created(tid, dept, to, text, parent_id)
        self.live.handoff(tid, "chief_of_staff" if parent_id else OWNER, to, "subtask" if parent_id else "request", text)
        if on_created:
            on_created(tid)
        if len(named) > 1:
            with self.Session() as db:
                self._post(db.get(Task, tid), None, f"You named {len(named)} shows ({', '.join(named)}). Each task belongs "
                           "to one show so their work never mixes — reply with the one show this task is for "
                           "(send the other as a separate message).")
            return tid
        if parent_id is None:
            self._maybe_standing_rule(tid, text)
            if self._dept_busy(dept, exclude=tid, show=show or (named[0] if len(named) == 1 else None)):
                with self.Session() as db:
                    t = db.get(Task, tid)
                    self._post(t, None, f"Queued — {dept} already has {self.max_open} tasks running. It starts automatically.")
                return tid   # stays RECEIVED; drain_queue() starts it when capacity frees (C41)
        if inherited_contract is not None:
            await self._adopt_inherited_contract(tid, inherited_contract)
        else:
            await self.draft_contract(tid)
        return tid

    async def steer(self, task_id: str, user: str, text: str) -> None:
        """Owner reply in a task thread. 'resume' continues an interrupted task; anything else is a
        one-off instruction -> new contract version -> back to G1 (the running loop notices and stops)."""
        self._maybe_standing_rule(task_id, text)
        with self.Session() as db:
            t = db.get(Task, task_id)
            if t.status in states.TERMINAL:
                self._post(t, None, "This task is closed — start a new message for new work.")
                return
            if t.status == "REJECTED":
                db.commit()
                await self.reject(task_id, user, text)   # the reply is the rejection reason (C35)
                return
            if t.status == "DELIVERED" and VERIFY.search(text):
                db.commit()
                await self.verify_on_request(task_id, user)   # 'verify' after delivery: Vera grades it now
                return
            asked = (t.contract or {}).get("_show_question")
            if t.status == "RECEIVED" and asked:
                pick = [x for x in asked if any(re.search(rf"\b{re.escape(w)}\b", text, re.I)
                                                for w in self.cfg.shows[x].get("triggers", []))]
                if len(pick) != 1:
                    db.commit()
                    self._post(t, None, f"Please reply with exactly one of: {', '.join(asked)}.")
                    return
                t.show, t.contract = pick[0], {}
                db.commit()
                picked = True
            else:
                picked = False
        if picked:
            await self.draft_contract(task_id)
            return
        with self.Session() as db:
            t = db.get(Task, task_id)
            clear_show = bool(t.show and t.parent_id is None and re.search(r"\bno show\b", text, re.I))
            named = [x for x in self.cfg.shows_named(text) if x != t.show]
            if len(named) > 1 or (named and t.parent_id is None and not re.search(r"\bswitch\b", text, re.I)):
                db.commit()   # a show name in a reply is never taken as a silent switch (I1)
                self._post(t, None, f"Your reply names {', '.join(named)}, but this task is for "
                                    f"{t.show or 'no show'}. Reply 'switch to <show>' to move it, or rephrase "
                                    "without the show name.")
                return
            if t.status == "RECEIVED" and text.strip().lower() in RESUME_WORDS and not asked:
                db.commit()
                await self.draft_contract(task_id)   # 'retry' after a connection failure: same request, no new note
                return
            if t.status == "ESCALATED" and text.strip().lower() in RESUME_WORDS and t.plan:
                states.transition(db, t, "IN_PROGRESS", user, "owner resumed")
                db.commit()
                resume = True
            else:
                resume = False
                c = dict(t.contract or {})
                c["_owner_notes"] = list(c.get("_owner_notes", [])) + [text]
                t.contract = c
                if t.status not in ("RECEIVED", "CONTRACT_DRAFTED"):
                    if "CONTRACT_DRAFTED" not in states.ALLOWED.get(t.status, set()):
                        db.commit()
                        self._post(t, None, f"Noted. I can't change direction while the task is {t.status}; "
                                            "I'll apply it at the next step.")
                        return
                    states.transition(db, t, "CONTRACT_DRAFTED", user, "owner changed direction")
                if len(named) == 1 and named[0] != t.show and t.parent_id is None:
                    t.show = named[0]   # the owner's latest word decides the show; the contract is redrafted
                elif clear_show:
                    t.show = None       # owner: the show detection was wrong ('video editor role at Jai Studios')
                for k in db.scalars(select(Task).where(Task.parent_id == t.id)):
                    if "CANCELLED" in states.ALLOWED.get(k.status, set()):   # C30: no orphaned sub-tasks
                        states.transition(db, k, "CANCELLED", user, "parent task changed direction")
                db.commit()
        if resume:
            await self.execute(task_id)
        else:
            await self.draft_contract(task_id)

    def _maybe_standing_rule(self, task_id: str, text: str) -> None:
        """'always / from now on / never' -> ask whether to save it as a standing rule (C23)."""
        if not STANDING.search(text or ""):
            return
        with self.Session() as db:
            t = db.get(Task, task_id)
            scope = (f"show:{t.show}" if t.show else
                     t.department if t.department in self.cfg.org["departments"] else "hq")   # I3
            m = MemoryEntry(id=f"mem_{uuid.uuid4().hex[:12]}", layer="L1", scope_id=scope, kind="preference",
                            content=text.strip()[:1000], source=f"owner:{t.slack_thread}", author="owner",
                            status="candidate", task_id=t.id, standing=True, confidence=1.0)
            db.add(m)
            a = Approval(id=_id("apr"), task_id=t.id, gate="GM", contract_version=t.contract_version,
                         preview={"memory_id": m.id})
            db.add(a)
            db.commit()
            self._post(t, None, "Standing rule?", blocks=approval_blocks(
                f"Save as a standing rule for {scope}?", f"> {text.strip()[:500]}\nApprove = remember for future tasks "
                "(expires after 180 days unused). Reject = only this task.", a.id))
            self.live.approval_requested(a.id, t.id, "GM", None, "Save as a standing rule?",
                                         f"{text.strip()[:500]}\nScope: {scope}")

    # ================================================================== approvals
    async def on_approval(self, user: str, approval_id: str, approve: bool, button_hash: str | None = None,
                          memory_ticks: list[str] | None = None, reason: str = "") -> str:
        with self.Session() as db:
            a = db.get(Approval, approval_id)
            if a is None or a.status not in ("pending", "confirming"):
                return "stale"
            t = db.get(Task, a.task_id)
            if a.gate != "GM" and a.contract_version != t.contract_version:
                a.status = "expired"
                db.commit()
                self.live.approval_closed(a.id, "expired")
                return "stale"
            if a.gate == "G3" and button_hash != a.action_hash:
                return "hash-mismatch"
            tier = a.tier if a.gate == "G3" else "OWNER"
            if not self.policy.can_approve(user, tier, t.department):
                db.add(AuditEvent(task_id=t.id, actor=user, kind="approval_denied", detail={"approval": a.id}))
                db.commit()
                return "not-an-approver"
            old = a.status
            if not approve:
                new = "rejected"
            elif a.gate == "G3" and a.tier == "R3" and old == "pending":
                new = "confirming"              # R3: approve, then confirm (C16)
            else:
                new = "approved"
            # atomic claim: only one click wins (C17)
            res = db.execute(update(Approval).where(Approval.id == a.id, Approval.status == old)
                             .values(status=new, decided_by=user, decided_at=datetime.now(timezone.utc)))
            if res.rowcount != 1:
                db.rollback()
                return "stale"
            db.add(AuditEvent(task_id=t.id, actor=user, kind=f"{a.gate}_{new}", detail={"approval": a.id}))
            gate, tid = a.gate, t.id
            if new == "confirming":   # R3 stays in the inbox until the second click
                self.live.approval_requested(a.id, t.id, "G3", (a.preview or {}).get("employee"), f"CONFIRM {a.action}",
                                             "Irreversible (R3). Approve again to confirm.", a.action_hash)
            else:
                self.live.approval_closed(a.id, new)
            back_to = (a.preview or {}).get("employee") if gate == "G3" else self.task_owner(t.department)
            if back_to and new != "confirming" and gate != "GM" and not (gate == "G4" and approve):
                self.live.handoff(tid, OWNER, back_to, "approved" if approve else "rejected", reason, gate=gate)
            if gate == "G1":
                if approve:
                    t.g1_approval_id = a.id
                    states.transition(db, t, "CONTRACT_APPROVED", user)
                else:
                    states.transition(db, t, "CANCELLED", user, "owner cancelled at G1")
            if gate == "GM":
                if approve:
                    new_m = db.get(MemoryEntry, a.preview["memory_id"])
                    old = self.memory.same_topic(db, new_m)
                    if old is not None:
                        new_m.supersedes = old.id   # C42: newer confirmed rule replaces the older one
                    self.memory.promote(db, a.preview["memory_id"], None, owner_ticked=True, by=user, owner_standing=True)
                else:
                    m = db.get(MemoryEntry, a.preview["memory_id"])
                    if m:
                        m.status = "rejected"
            db.commit()
            if new == "confirming":
                self._post(t, None, "Confirm irreversible action", blocks=approval_blocks(
                    f"G3 · CONFIRM {a.action} (R3, irreversible)", "Click Approve again to confirm.", a.id,
                    action_hash=a.action_hash))
                return "confirm-needed"
        if gate == "G1" and approve:
            await self.plan(tid)
        elif gate == "G1":
            await self._child_finished_if_any(tid)
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
        await self._child_finished_if_any(task_id)

    # ================================================================== execute (agent-harness)
    def _new_round(self, task_id: str) -> None:
        """Archive the previous round's plan-task folders and artifacts (C19). Dept inputs (X-*) stay."""
        w = task_dir(task_id)
        old = [p for p in w.glob("T*") if p.is_dir()]
        arts = w / "artifacts"
        prev = [p for p in arts.glob("*") if not p.name.startswith("X-")] if arts.exists() else []
        if old or prev:
            n = len(list((w / "rounds").glob("r*"))) + 1 if (w / "rounds").exists() else 1
            dest = w / "rounds" / f"r{n}"
            (dest / "artifacts").mkdir(parents=True, exist_ok=True)
            for p in old:
                shutil.move(str(p), str(dest / p.name))
            for p in prev:
                shutil.move(str(p), str(dest / "artifacts" / p.name))
        arts.mkdir(parents=True, exist_ok=True)
        if not (w / "sources.json").exists():
            (w / "sources.json").write_text(json.dumps({"urls": [], "memory_ids": [], "pointers": []}))
        # C44: the owner's request, the approved contract and each handoff are legitimate, observed sources
        self._add_source(task_id, "pointers", ["owner:request", "contract"] + [f"handoff:T{i}" for i in range(1, 21)])

    def _still_current(self, task_id: str, version: int) -> bool:
        with self.Session() as db:
            t = db.get(Task, task_id)
            return t.status == "IN_PROGRESS" and t.contract_version == version

    async def execute(self, task_id: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            if t.status == "PLANNED":
                states.transition(db, t, "IN_PROGRESS", "dispatcher")
            elif t.status == "REVISION":
                states.transition(db, t, "IN_PROGRESS", "dispatcher", "revision round")
            if t.status != "IN_PROGRESS":
                db.commit()
                return
            route_checks, resolved = {}, {}
            for i, h in enumerate(t.plan, 1):
                r = resolve(self.cfg, h["to"], h["task_type"], h.get("skill_required", False), self.brand_kit)
                route_checks[f"T{i}"] = r.checks
                resolved[f"T{i}"] = r
            plan = self.harness.build_plan(t.id, t.contract["objective"], t.department, t.plan, route_checks)
            version = t.contract_version
            db.commit()
            packets = list(t.plan)
        self._active.add(task_id)
        try:
            self._new_round(task_id)
            self.harness.init(task_id, plan)
            failures: dict[str, list[str]] = {}
            while True:
                if not self._still_current(task_id, version):
                    return  # owner steered / cancelled / budget stop: this loop is obsolete (C18)
                d = self.harness.next(task_id)
                if d.action == "execute":
                    pt = d.task
                    h = packets[int(pt[1:]) - 1]
                    attempt = len(failures.get(pt, [])) + 1
                    self.live.handoff(task_id, h["from"], h["to"], "assign", h["objective"], step=pt, attempt=attempt,
                                      task_type=h["task_type"])
                    outcome = await self._run_specialist(task_id, pt, packets, resolved[pt], failures.get(pt, []))
                    passed = False
                    if outcome["status"] == "blocked":
                        with self.Session() as db:
                            t = db.get(Task, task_id)
                            states.transition(db, t, "ESCALATED", packets[int(pt[1:]) - 1]["to"], "specialist blocked / unsure")
                            db.commit()
                            qs = "\n".join(f"• {q}" for q in outcome.get("questions") or []) or "• (no questions given)"
                            self._post(t, self.cfg.employee(packets[int(pt[1:]) - 1]["to"]),
                                       f"I stopped instead of guessing ({outcome['why']}). I need:\n{qs}\n"
                                       "Reply in this thread to redirect.")
                        return
                    self.harness.record_execute(task_id, pt, outcome["status"] == "ok")
                    if outcome["status"] == "ok":
                        result, _ = self.harness.verify(task_id, pt)
                        passed = result.get("status") == "verified"
                        if not passed:
                            failed = [{"check": f["cmd"].split(" ")[3] if f["cmd"].startswith("python3 -m") else f["cmd"],
                                       "output": f.get("tail")} for f in result.get("failed_checks", [])]
                            failures.setdefault(pt, []).append(json.dumps(failed or result)[:1500])
                    else:
                        failures.setdefault(pt, []).append(outcome.get("why", "no valid return packet"))
                    self.live.handoff(task_id, h["to"], h["from"], "return", outcome.get("summary", ""), step=pt,
                                      attempt=attempt, checks_passed=passed)
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
                with self.Session() as db:
                    t = db.get(Task, task_id)
                    states.transition(db, t, "ESCALATED", "harness", json.dumps(d.detail)[:500])
                    db.commit()
                    self._post(t, None, f"⚠️ Escalated: {d.detail.get('detail', d.action)}. Reply in this thread to "
                                        "change direction, or 'resume' to try again.")
                return
        finally:
            self._active.discard(task_id)
        await self.verify(task_id)

    def _upstream(self, task_id: str, packets: list[dict], handoff: dict) -> tuple[set[str], list[str]]:
        """Refs + summaries of the outputs this handoff depends on (C2)."""
        refs, summaries = set(handoff.get("inputs") or []), []
        for dep in handoff.get("inputs_from") or []:
            rp = plan_task_dir(task_id, dep) / "return.json"
            if rp.exists():
                r = json.loads(rp.read_text())
                refs |= set(r.get("outputs", []))
                summaries.append(untrusted(f"upstream:{dep}", dep, f"from {r.get('from')}: {r.get('summary', '')}\n"
                                                                    f"outputs: {r.get('outputs', [])}"))
        return refs, summaries

    async def _run_specialist(self, task_id: str, pt: str, packets: list[dict], route, failures: list[str]) -> dict:
        handoff = packets[int(pt[1:]) - 1]
        emp = self.cfg.employee(handoff["to"])
        d = plan_task_dir(task_id, pt)
        (d / "artifacts").mkdir(parents=True, exist_ok=True)
        (d / "handoff.json").write_text(json.dumps(handoff, indent=2))
        (d / "spec.json").write_text(json.dumps(handoff.get("spec") or {}))
        allowed, summaries = self._upstream(task_id, packets, handoff)
        with self.Session() as db:
            show = db.get(Task, task_id).show
            mem = self.memory.read(db, emp, handoff["objective"], show=show)
            db.commit()
        system = system_prompt(self.cfg, emp, "execute", route, mem, show=show)
        prompt = "Handoff packet:\n" + json.dumps({k: v for k, v in handoff.items() if k != "task_id"}, indent=1)
        with self.Session() as db:
            tc = db.get(Task, task_id).contract or {}
            owner_rules = list(tc.get("one_off_instructions") or []) + list(tc.get("_owner_notes") or [])
            constraints = list(tc.get("constraints") or [])
            revision = tc.get("_revision_notes")
        if owner_rules or constraints:   # C39: the owner's words go to every specialist verbatim
            prompt += "\n\nOwner instructions for this task (must follow):\n" + "\n".join(
                owner_request(f"rule{i}", r) for i, r in enumerate(owner_rules + constraints))
        if revision:
            prompt += ("\n\nREVISION — the previous delivery was rejected for these reasons. Fix exactly these:\n"
                       + untrusted("review", "verifier", revision))
        prompt += ("\n\nYour output artifact must contain ONLY the deliverable itself (C45): no drafts labels, notes, "
                   "gaps, assumptions or metadata — put those in summary/open_questions. Do only your own deliverable, "
                   "not other specialists' parts.")
        prompt += f"\n\nYour artifacts are saved as {pt}-<name>. You may read: {sorted(allowed) or 'nothing upstream'}."
        if "sandbox.exec" in emp.tools:
            prompt += ("\nYou build in a sandbox project (project_write / project_import / run_command). Save finished "
                       "files with export_output and list the MAIN output (e.g. the rendered MP4) FIRST in outputs — "
                       "your checks run on it.")
        facts = self.cfg.owner_facts(emp.id)
        if facts:
            self._add_source(task_id, "pointers", [f"context:{emp.id}"])
        prompt += (f"\nCite sources ONLY with these exact keys: owner:request, contract, handoff:{pt}, artifact://<ref> you read, "
                   "memory:<id> you read, or a URL you actually fetched"
                   + (f", or context:{emp.id} for the Owner facts in your training" if facts else "")
                   + ". Style/craft choices need no citation.")
        if summaries:
            prompt += "\n\nUpstream work:\n" + "\n".join(summaries)
        if failures:
            prompt += "\n\nPrevious attempt failed these checks — change your approach:\n" + "\n".join(failures[-2:])
        sink: dict = {}
        ctx = {"untrusted": False, "pt": pt}
        tools = self._common_tools(emp, task_id, pt, allowed, ctx)
        if route and route.skills and "skill.read" in emp.tools:
            tools.append(self._skill_read_tool(route))
        tools.append(self._submit_return_tool(emp, task_id, pt, sink, ctx))
        tools.append(self._act_tool(emp, task_id))
        tools += self._upload_tools(emp, task_id)
        tools += self._pipeline_tools(emp, task_id)
        if "email.read" in emp.tools:
            tools += self._email_tools(emp, task_id)
        if "sandbox.exec" in emp.tools:
            tools += self._build_tools(emp, task_id, pt, allowed, ctx)
        await self._run(emp, task_id, "execute", system, prompt, tools, ctx, route=route, attempt=len(failures) + 1)
        rp = sink.get("return")
        if not rp:
            return {"status": "fail", "why": "You did not call submit_return with a valid return packet."}
        (d / "return.json").write_text(json.dumps(rp, indent=2))
        if rp["status"] in ("blocked", "out_of_scope") or float(rp.get("confidence", 0)) < LOW_CONFIDENCE:
            why = rp["status"] if rp["status"] in ("blocked", "out_of_scope") else f"confidence {rp.get('confidence')}"
            return {"status": "blocked", "why": why, "questions": rp.get("open_questions") or []}
        outs = [o.split("/")[-1] for o in rp.get("outputs", [])]
        art = task_dir(task_id) / "artifacts"
        for name in outs:
            shutil.copy(art / name, d / "artifacts" / name)
        if outs:
            shutil.copy(art / outs[0], d / "primary")
        return {"status": "ok"}

    # ================================================================== runner + budgets
    async def _run(self, emp: Employee, task_id: str, phase: str, system: str, prompt: str,
                   tools: list[ToolSpec], ctx: dict | None = None, no_web: bool = False, route=None,
                   attempt: int = 1) -> RunResult:
        with self.Session() as db:
            t = db.get(Task, task_id)
            paused = self.policy.paused(db, emp)
            cap = float(self.task_caps.get(t.size or "S", self.task_caps["S"]))
            month_left = self.monthly_budget - self.policy.counter_value(db, f"month:{_month()}", "plan", "llm_usd")
            remaining = max(0.0, min(cap - t.cost_usd, month_left))   # C38: one run can't overshoot the plan credit
            model = self.cfg.model_for(emp, attempt, t.size)          # ORG-V3 §3b: retries climb the ladder
            db.commit()
        if paused:
            return RunResult(is_error=True, text=paused)
        if remaining <= 0:
            return RunResult(is_error=True, text="task budget exhausted")
        builtins = {} if no_web else {name: action for name, action in BUILTINS.items() if action in emp.tools}

        async def gate(tool_name: str, tool_input: dict) -> tuple[bool, str]:
            action = builtins[tool_name]
            params = {"url": tool_input.get("url")} if action == "web.fetch" else {"query": tool_input.get("query")}
            dec = self._check(emp, task_id, action, params)
            if dec.allowed and action == "web.fetch":
                with self.Session() as db:
                    db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="fetched", detail={"url": params["url"]}))
                    db.commit()
                self._add_source(task_id, "urls", [params["url"]])
                if ctx is not None:
                    ctx["untrusted"] = True
            elif dec.allowed and ctx is not None:
                ctx["untrusted"] = True
            return dec.allowed, dec.reason

        guarded = [self._guard(emp, task_id, t) for t in tools]
        self.live.run_started(emp.id, task_id, phase)
        try:
            res = await self.runner.run(employee_id=emp.id, model=model, phase=phase, system=system, prompt=prompt,
                                        tools=guarded, builtins=builtins, gate=gate, max_turns=30, budget_usd=remaining,
                                        effort=self.cfg.effort_for(emp, phase, route),
                                        fallback_model=self.cfg.fallback_for(model),
                                        advisor=self.cfg.advisor_for(route.task_type if route else None))
        except Exception as e:  # noqa: BLE001 — SDK/CLI failures must not crash the dispatcher
            res = RunResult(is_error=True, text=f"{type(e).__name__}: {e}")
        with self.Session() as db:
            t = db.get(Task, task_id)
            t.cost_usd += res.cost_usd
            spent = self.policy.bump(db, f"month:{_month()}", "plan", "llm_usd", res.cost_usd)
            db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="agent_run",
                              detail={"phase": phase, "model": model, "attempt": attempt, "cost": res.cost_usd,
                                      "error": res.is_error, "text": res.text[:300]}))
            if spent >= self.monthly_budget:
                self.policy.pause(db, "all", f"budget:{_month()}: monthly plan credit (${self.monthly_budget:.0f}) used", "budget")
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
            if t.cost_usd >= cap and t.status == "IN_PROGRESS":
                states.transition(db, t, "ESCALATED", "budget", f"task budget ${cap} used")
                db.commit()
                self._post(t, None, f"⚠️ Task budget (${cap}) used up — escalating. Reply to redirect or cancel.")
                return True
        return False

    # ================================================================== slack out
    def _post(self, t: Task, emp: Employee | None, text: str, blocks: list | None = None) -> None:
        persona = {"name": emp.name, "icon_emoji": ":robot_face:"} if emp else {"name": "Dispatcher", "icon_emoji": ":gear:"}
        self.live.said(t.id, emp.id if emp else None, text)
        try:
            self.slack.post(t.slack_channel or self.cfg.owner_id, text, t.slack_thread, persona, blocks)
        except Exception as e:  # noqa: BLE001 — Slack outage must not lose task state
            print(f"[workforce] slack post failed: {e}")

    # ================================================================== owner commands
    def command(self, user: str, text: str) -> str:
        if user != self.cfg.owner_id:
            return "Only the owner can run commands."
        parts = text.strip().split()
        if not parts:
            return ("commands: pause-all | pause <emp|dept> | resume <all|emp|dept> | status | gc | sweep | "
                    "hire <proposal file> | end-probation <employee id>")
        cmd = parts[0].lstrip("/")
        if cmd == "hire" and len(parts) > 1:
            return self.hire(parts[1])
        if cmd == "end-probation" and len(parts) > 1:
            return self.end_probation(parts[1])
        if cmd == "sweep":
            return f"Sweep: {self.sweep()}"
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


def is_chitchat(text: str) -> bool:
    """C40: acknowledgements aren't work requests (they'd otherwise start a paid task)."""
    t = (text or "").strip()
    return bool(CHITCHAT.match(t)) or len(re.findall(r"\w+", t)) < 2


# Re-exported: tests and callers import these from workforce.dispatcher.
__all__ = ["BUILTINS", "Dispatcher", "is_chitchat", "normalize_ids", "validate_contract",
           "validate_pending_actions", "validate_plan"]
