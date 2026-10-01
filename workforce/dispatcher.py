"""The Dispatcher: deterministic code that runs the workforce (DESIGN-MAP §4–§10, §20).

Owner message -> Lead drafts contract with assignee + task_type per deliverable (G1) -> Lead plans
handoffs (must match the contract, cover every criterion, fit the size) -> agent-harness loop runs each
specialist, passing upstream outputs forward, and verifies with machine checks -> LLM Verifier when §7
requires (incl. any numbers/claims) -> Lead delivery note from real summaries -> owner accepts (G4,
memory ticks) -> R2/R3 actions as hash-bound G3 approvals (R3 double-confirm).

Every tool call from every agent goes through `_guard` -> Policy.check -> audit.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import states
from .agents import AgentRunner, RunResult, ToolSpec, err, ok
from .config import ROOT, TIER, Config, Employee
from .db import Approval, AuditEvent, MemoryEntry, Pause, Task
from .harness import Harness, HarnessError, plan_task_dir, task_dir
from .live import OWNER, LiveBus
from .memory import MemoryStore
from .pii import find_pii
from .policy import ALLOW, APPROVAL, Policy, action_hash
from .prompts import owner_request, show_allowed, system_prompt, untrusted
from .routing import RouteError, resolve
from .slack import InboundMessage, SlackClient, approval_blocks

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
BUILTINS = {"WebSearch": "web.search", "WebFetch": "web.fetch"}
CRITERION_CHECKS = {"automatic", "verifier", "owner_taste"}
TOOL_ACTIONS = {
    "workspace_write": "workspace.write", "workspace_read": "workspace.read", "memory_read": "memory.read_scoped",
    "slack_post": "slack.post_own_thread", "submit_contract": "submit_contract", "submit_plan": "submit_plan",
    "submit_return": "submit_return", "submit_verdict": "submit_verdict", "submit_delivery": "submit_delivery",
    "submit_factcheck": "submit_factcheck",
}
SIZE_LIMIT = {"S": 1, "M": 3, "L": 20}
CLAIM = re.compile(r"(\$\s?\d|€\s?\d|£\s?\d|₹\s?\d|\b\d+(?:\.\d+)?\s?%|\b(?:19|20)\d{2}\b|\b\d{2,}(?:[.,]\d+)?\b)")
VERIFY = re.compile(r"\b(verify|verified|verifier|vera|double[- ]check)\b", re.I)
# A standing-rule phrase, or "always/never" used as an instruction: at the start of a sentence or after
# please/you/we/just ("never use Hindi words") — not inside a topic ("why you should never skip breakfast").
STANDING = re.compile(r"\b(?:from now on|going forward|every time|in (?:the )?future|by default)\b|"
                      r"(?:^|[.!?:;\n]\s*|\b(?:please|pls|you|we|just|and)\s+)(?:always|never)\b(?!-)", re.I)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
URL = re.compile(r"https?://\S+")
PROSE_SUFFIXES = {"", ".md", ".txt", ".html", ".csv", ".srt", ".vtt"}   # json/yaml project files aren't claims
PIPELINE_STATUSES = {"sent", "ready_to_send", "replied_positive", "replied_negative", "no_reply", "follow_up_sent",
                     "interview", "offer", "closed"}
PIPELINE_KIND = {("*", "email.send_external"): "pitch", ("*", "apply.submit"): "application", ("*", "invoice.send"): "invoice"}
FOLLOW_UP_DAYS = {"pitch": 5, "application": 7, "follow_up": 7, "invoice": 14}
INFRA = re.compile(r"authenticat|unauthori[sz]ed|401|403|rate.?limit|overloaded|network|timed? ?out|connection|"
                   r"CLINotFound|ProcessError|budget exhausted|paused", re.I)
RESUME_WORDS = {"resume", "retry", "continue", "go on"}
LOW_CONFIDENCE = 0.6
IN_FLIGHT = ("PLANNED", "IN_PROGRESS", "VERIFYING", "REVISION")
TEXT_SUFFIXES = {"", ".md", ".txt", ".json", ".html", ".csv", ".srt", ".vtt", ".yaml", ".yml"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


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
            system = system_prompt(self.cfg, emp, "contract", None,
                                   self.memory.read(db, emp, t.original_request, show=t.show), show=t.show)
            db.commit()
        sink: dict = {}
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
                                   self.memory.read(db, emp, t.original_request, show=t.show), show=t.show)
            db.commit()
        sink: dict = {}
        await self._run(emp, task_id, "plan", system, prompt, [self._submit_plan_tool(emp, task_id, sink)])
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
        if mem:   # memory shown in the prompt is something this specialist observed: it may cite it
            self._add_source(task_id, "memory_ids", [m.id for m in mem], pt)
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
            self._add_source(task_id, "pointers", [f"context:{emp.id}"], pt)
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
        tools.append(self._submit_return_tool(emp, task_id, pt, sink, ctx))
        tools.append(self._act_tool(emp, task_id))
        if route.skills or route.support:
            tools.append(self._skill_read_tool(list(route.skills) + list(route.support)))
        tools += self._upload_tools(emp, task_id, pt)
        tools += self._pipeline_tools(emp, task_id, pt)
        if "email.read" in emp.tools:
            tools += self._email_tools(emp, task_id, pt)
        if "sandbox.exec" in emp.tools:
            tools += self._build_tools(emp, task_id, pt, allowed, ctx)
        await self._run(emp, task_id, "execute", system, prompt, tools, ctx)
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

    # ------------------------------------------------------------------ tools given to agents
    def _skill_read_tool(self, allowed: list[str]) -> ToolSpec:
        """Read-only access to the files of THIS route's skills (+ support skills) — nothing else on disk."""
        from .routing import skill_file, skill_files

        async def handler(args):
            name, rel = str(args.get("skill", "")), str(args.get("path") or "")
            if name not in allowed:
                return err(f"'{name}' isn't one of your skills for this task: {allowed}")
            if not rel:
                return ok("\n".join(skill_files(name)) or "no files")
            text = skill_file(name, rel)
            if text is None:
                return err(f"no such text file in {name}; call skill_read with only the skill name to list its files")
            return ok(text)
        return ToolSpec("skill_read", "Open one file of a skill you were given (omit path to list its files).",
                        {"type": "object", "properties": {"skill": {"type": "string", "enum": allowed},
                         "path": {"type": "string"}}, "required": ["skill"]}, handler)

    def _check(self, emp: Employee, task_id: str, action: str, params: dict | None = None):
        with self.Session() as db:
            t = db.get(Task, task_id)
            dec = self.policy.check(db, emp, action, params or {}, t)
            db.commit()
        return dec

    def _guard(self, emp: Employee, task_id: str, spec: ToolSpec) -> ToolSpec:
        """C1: every Dispatcher tool is permission-checked and audited before it runs."""
        action = TOOL_ACTIONS.get(spec.name)
        inner = spec.handler

        async def guarded(args: dict) -> dict:
            if action:
                dec = self._check(emp, task_id, action, {"tool": spec.name})
                if not dec.allowed:
                    return err(f"denied by policy: {dec.reason}")
            return await inner(args)
        return ToolSpec(spec.name, spec.description, spec.schema, guarded)

    def _unobserved_citations(self, task_id: str, citations: list, pt: str | None = None) -> list[str]:
        """With `pt`: only what THIS plan task observed (its own fetches, reads, memory, artifacts it opened or wrote)
        plus the shared task sources — never what a sibling specialist saw. Without `pt` (Proof): the whole task."""
        p = (plan_task_dir(task_id, pt) if pt else task_dir(task_id)) / "sources.json"
        seen = json.loads(p.read_text()) if p.exists() else {}
        observed = set(seen.get("urls", [])) | set(seen.get("pointers", [])) | {f"memory:{m}" for m in seen.get("memory_ids", [])}
        if pt:
            observed |= {"owner:request", "contract", f"handoff:{pt}"}
        arts = task_dir(task_id) / "artifacts"
        bad = []
        for c in citations:
            src = str(c.get("source", "")) if isinstance(c, dict) else str(c)
            if src.startswith("artifact://"):
                name = src.split("/")[-1]
                if (arts / name).exists() and (not pt or name.startswith(f"{pt}-") or f"artifact://{name}" in observed):
                    continue
            elif src in observed:
                continue
            bad.append(src)
        return bad

    def _add_source(self, task_id: str, kind: str, values: list[str], pt: str | None = None) -> None:
        """Record what was observed: task-wide (Proof checks against it) and, with `pt`, for that plan task only."""
        for p in [task_dir(task_id) / "sources.json"] + ([plan_task_dir(task_id, pt) / "sources.json"] if pt else []):
            p.parent.mkdir(parents=True, exist_ok=True)
            data = json.loads(p.read_text()) if p.exists() else {"urls": [], "memory_ids": [], "pointers": []}
            data[kind] = sorted(set(data.get(kind, [])) | set(values))
            p.write_text(json.dumps(data))

    def _common_tools(self, emp: Employee, task_id: str, pt: str, allowed_inputs: set[str], ctx: dict) -> list[ToolSpec]:
        art = task_dir(task_id) / "artifacts"
        art.mkdir(parents=True, exist_ok=True)
        prefix = f"{pt}-"

        async def ws_write(args):
            if len(str(args.get("content", ""))) > 2_000_000:
                return err("artifact too large (2 MB text limit) — split it (C33)")
            name = prefix + SAFE_NAME.sub("_", str(args["name"]).split("/")[-1]).removeprefix(prefix)[:100]
            (art / name).write_text(str(args["content"]))
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="artifact", detail={"name": name, "pt": pt}))
                db.commit()
            self.live.publish("artifact.created", task_id, employee_id=emp.id, name=name, step=pt)
            return ok(f"saved artifact://{task_id}/{name}")

        async def ws_read(args):
            ref = str(args["ref"])
            name = SAFE_NAME.sub("_", ref.split("/")[-1])
            allowed_names = {r.split("/")[-1] for r in allowed_inputs}
            if not (name.startswith(prefix) or name in allowed_names):
                return err("you may only read your own artifacts or the upstream ones listed in your prompt")
            p = art / name
            if not p.exists():
                return err("no such artifact")
            if not name.startswith(prefix):
                ctx["untrusted"] = True  # another employee's output (C13)
                self._add_source(task_id, "pointers", [f"artifact://{name}"], pt)
            return ok(untrusted("artifact", name, p.read_text(errors="replace")[:50_000]))

        async def mem_read(args):
            with self.Session() as db:
                rows = self.memory.read(db, emp, str(args.get("query", "")), show=db.get(Task, task_id).show)
                db.commit()
                ids = [m.id for m in rows]
                lines = [f"[{m.id}] {m.content}" for m in rows]
            self._add_source(task_id, "memory_ids", ids, pt)
            return ok("\n".join(lines) or "nothing relevant")

        async def slack_post(args):
            with self.Session() as db:
                t = db.get(Task, task_id)
                self._post(t, emp, str(args["text"])[:3000])
            return ok("posted in the task thread")

        tools = [
            ToolSpec("workspace_write", f"Save an output artifact (text). Stored as {prefix}<name>.",
                     {"type": "object", "properties": {"name": {"type": "string"}, "content": {"type": "string"}}, "required": ["name", "content"]}, ws_write),
            ToolSpec("workspace_read", "Read an artifact by artifact:// ref (your own, or upstream refs listed in your prompt).",
                     {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}, ws_read),
            ToolSpec("memory_read", "Search your permitted memory. Cite results as memory:<id>.",
                     {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, mem_read),
        ]
        if "slack.post_own_thread" in emp.tools:
            tools.append(ToolSpec("slack_post", "Post a short progress note in the task thread.",
                                  {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, slack_post))
        return tools

    # ------------------------------------------------------------------ pipeline (every pitch/application sent)
    def _pipeline_tools(self, emp: Employee, task_id: str, pt: str | None = None) -> list[ToolSpec]:
        from .db import PipelineItem
        tools = []
        if "pipeline.read" in emp.tools:
            async def pread(args):
                q = str(args.get("query") or "").lower()
                with self.Session() as db:
                    rows = [r for r in db.scalars(select(PipelineItem).order_by(PipelineItem.sent_at.desc()))
                            if not q or q in f"{r.to} {r.subject} {r.kind} {r.status}".lower()][:40]
                    out = [{"id": r.id, "kind": r.kind, "to": r.to, "subject": r.subject, "status": r.status,
                            "sent": str(r.sent_at)[:10], "follow_up_due": str(r.follow_up_due)[:10] if r.follow_up_due else None,
                            "note": r.note, "body": r.body[:1500]} for r in rows]
                self._add_source(task_id, "pointers", [f"pipeline:{r['id']}" for r in out], pt)
                return ok(untrusted("pipeline", "rows", json.dumps(out, indent=1)) if out else "pipeline is empty")
            tools.append(ToolSpec("pipeline_read", "Read your pitch/application pipeline (optional text filter). Cite rows as pipeline:<id>.",
                                  {"type": "object", "properties": {"query": {"type": "string"}}}, pread))
        if "pipeline.update" in emp.tools:
            async def pupdate(args):
                st = str(args.get("status", ""))
                if st not in PIPELINE_STATUSES:
                    return err(f"status must be one of {sorted(PIPELINE_STATUSES)}")
                with self.Session() as db:
                    r = db.get(PipelineItem, str(args.get("id")))
                    if r is None:
                        return err("no such pipeline row (rows are created only when something is actually sent)")
                    r.status, r.note = st, str(args.get("note") or r.note)[:2000]
                    if args.get("follow_up_due"):
                        try:
                            r.follow_up_due = datetime.fromisoformat(str(args["follow_up_due"])).replace(tzinfo=timezone.utc)
                        except ValueError:
                            return err("follow_up_due must be YYYY-MM-DD")
                    db.commit()
                return ok(f"{r.id} -> {st}")
            tools.append(ToolSpec("pipeline_update", "Set a pipeline row's status, note and next follow-up date.",
                                  {"type": "object", "properties": {"id": {"type": "string"}, "status": {"type": "string",
                                   "enum": sorted(PIPELINE_STATUSES)}, "note": {"type": "string"},
                                   "follow_up_due": {"type": "string"}}, "required": ["id", "status"]}, pupdate))
        return tools

    # ------------------------------------------------------------------ inbox (read-only)
    def _email_tools(self, emp: Employee, task_id: str, pt: str | None = None) -> list[ToolSpec]:
        reader = self.email_reader

        async def elist(args):
            if not reader.configured():
                return err("no email connector configured (IMAP_HOST/IMAP_USER/IMAP_PASSWORD) — return blocked and tell the owner")
            hours = max(1, min(48, int(args.get("hours") or 24)))
            rows = reader.list_recent(hours)
            self._add_source(task_id, "pointers", [f"email_listed:{r['id']}" for r in rows], pt)
            return ok(json.dumps(rows, indent=1) if rows else "no email in that window")

        async def eopen(args):
            if not reader.configured():
                return err("no email connector configured")
            m = reader.open(str(args.get("id")))
            self._add_source(task_id, "pointers", [f"email:{m['id']}"], pt)
            return ok(untrusted("email", m["id"], json.dumps(m, indent=1)))
        return [ToolSpec("email_list", "List emails from the last N hours (headers only). Open EVERY one with email_open.",
                         {"type": "object", "properties": {"hours": {"type": "integer"}}}, elist),
                ToolSpec("email_open", "Open one email by id (read-only; never marks it read). Cite it as email:<id>.",
                         {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, eopen)]

    # ------------------------------------------------------------------ uploads (your files, per scope)
    def _upload_tools(self, emp: Employee, task_id: str, pt: str | None = None) -> list[ToolSpec]:
        from . import uploads
        scopes = uploads.scopes_for(self.cfg, emp)
        if not scopes:
            return []

        async def up_list(args):
            return ok("\n".join(f"{s}/{n}" for s in scopes for n in uploads.listing(s)) or "no files yet — ask the owner")

        async def up_read(args):
            scope, _, name = str(args.get("ref", "")).removeprefix("upload:").partition("/")
            if scope not in scopes:
                return err(f"you can't read '{scope}' files (yours: {scopes})")
            p = uploads.path(scope, name)
            if p is None:
                return err("no such file — ask the owner to add it (never invent its contents)")
            self._add_source(task_id, "pointers", [f"upload:{scope}/{p.name}"], pt)
            try:
                text = p.read_bytes()[:200_000].decode("utf-8")
            except UnicodeDecodeError:
                return ok(f"{p.name} is a binary file ({p.stat().st_size} bytes) — import it into your project instead")
            return ok(untrusted("upload", f"{scope}/{p.name}", text))
        return [ToolSpec("uploads_list", f"List the owner's files you may use (scopes: {scopes}).", {"type": "object", "properties": {}}, up_list),
                ToolSpec("uploads_read", "Read a text file the owner uploaded: ref 'upload:<scope>/<name>'. Cite it as that ref.",
                         {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}, up_read)]

    # ------------------------------------------------------------------ build tools (producers, designers, engineers)
    def _build_tools(self, emp: Employee, task_id: str, pt: str, allowed_inputs: set[str], ctx: dict) -> list[ToolSpec]:
        from . import runtime, uploads
        project = plan_task_dir(task_id, pt) / "project"
        show_dir = (self.cfg.shows.get(emp.show) or {}).get("dir") if emp.show else None
        runtime.seed_project(project, show_dir)
        work = "code" if "code.write" in emp.tools else "video"
        art = task_dir(task_id) / "artifacts"

        def inside(rel: str) -> Path | None:
            p = (project / rel).resolve()
            return p if str(p).startswith(str(project.resolve())) and "/.." not in rel else None

        async def pwrite(args):
            p = inside(str(args.get("path", "")))
            if p is None:
                return err("path must stay inside your project")
            if len(str(args.get("content", ""))) > 2_000_000:
                return err("file too large (2 MB text)")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(args.get("content", "")))
            return ok(f"wrote {p.relative_to(project)}")

        async def pread(args):
            p = inside(str(args.get("path", "")))
            if p is None or not p.exists():
                return err("no such file in your project")
            if p.is_dir():
                return ok("\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir()))[:6000])
            return ok(p.read_text(errors="replace")[:50_000])

        async def pimport(args):
            ref, dest = str(args.get("ref", "")), inside(str(args.get("dest", "")))
            if dest is None:
                return err("dest must stay inside your project")
            if ref.startswith("upload:"):
                scope, _, name = ref[7:].partition("/")
                if not uploads.can_read(self.cfg, emp, scope):
                    return err(f"you can't use '{scope}' files")
                src = uploads.path(scope, name)
            else:
                name = ref.split("/")[-1]
                src = art / name if name in {r.split("/")[-1] for r in allowed_inputs} else None
            if src is None or not src.exists():
                return err("not found, or not an input you were given — ask the owner for missing assets")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dest)
            return ok(f"copied to {dest.relative_to(project)}")

        async def prun(args):
            dec = self._check(emp, task_id, "sandbox.exec", {"cost_usd": 0.0})
            if not dec.allowed:
                return err(f"denied by policy: {dec.reason}")
            try:
                argv = runtime.parse_command(str(args.get("command", "")), work, show_dir)
            except runtime.RuntimeError_ as e:
                return err(str(e))
            cwd = inside(str(args.get("cwd") or "."))
            if cwd is None or not cwd.is_dir():
                return err("cwd must be a folder inside your project")
            res = runtime.run(cwd, argv, timeout=int(args.get("timeout") or 900))
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="sandbox_exec",
                                  detail={"argv": argv, "exit": res.exit_code}))
                db.commit()
            return ok(f"exit {res.exit_code}\n{res.output}")

        async def pexport(args):
            p = inside(str(args.get("path", "")))
            if p is None or not p.is_file():
                return err("no such file in your project")
            name = f"{pt}-" + SAFE_NAME.sub("_", str(args.get("name") or p.name)).removeprefix(f"{pt}-")[:100]
            if p.stat().st_size > 500 * 1024 * 1024:
                return err("file too large (500 MB)")
            shutil.copy(p, art / name)
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="artifact", detail={"name": name, "pt": pt}))
                db.commit()
            return ok(f"saved artifact://{task_id}/{name}")

        tools = [
            ToolSpec("project_write", "Write a text file in your sandbox project (path relative to it).",
                     {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}, pwrite),
            ToolSpec("project_read", "Read a file, or list a folder, in your sandbox project.",
                     {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, pread),
            ToolSpec("project_import", "Copy an upstream artifact (artifact://… listed in your prompt) or an owner upload "
                     "(upload:<scope>/<name>) into your project.",
                     {"type": "object", "properties": {"ref": {"type": "string"}, "dest": {"type": "string"}},
                      "required": ["ref", "dest"]}, pimport),
            ToolSpec("run_command", "Run ONE allowlisted command in your project (no shell). Video: npx hyperframes@<v> "
                     "<init|check|snapshot|render|…>, python3 core/reel.py <your-show> <new|assets|build|data|sfx>. "
                     "Code: npm test|ci|install|run build, node, python3 -m pytest.",
                     {"type": "object", "properties": {"command": {"type": "string"}, "cwd": {"type": "string"},
                                                       "timeout": {"type": "integer"}}, "required": ["command"]}, prun),
            ToolSpec("export_output", "Save a finished file from your project (e.g. the MP4) as your output artifact.",
                     {"type": "object", "properties": {"path": {"type": "string"}, "name": {"type": "string"}},
                      "required": ["path"]}, pexport),
        ]
        if "voice.synthesize" in emp.tools:
            tools.append(self._voice_tool(emp, task_id, project, inside))
        return tools

    def _voice_tool(self, emp: Employee, task_id: str, project: Path, inside) -> ToolSpec:
        """The voice is chosen by the Dispatcher from the show — the employee can't pick another (I5)."""
        from . import runtime
        spec = self.cfg.shows.get(emp.show) or {}
        base = self.cfg.org["runtime"].get("default_base_voice", {})
        kind = spec.get("voice", "base") if emp.show else "base"
        engine = spec.get("voice_engine") or base.get("engine", "kokoro")
        voice_id = spec.get("voice_id") or (None if emp.show else base.get("voice_id"))
        show_dir = ROOT / spec.get("dir", "") if emp.show else None
        settings = {}
        if show_dir is not None and (show_dir / "voice" / "VOICE.json").exists():
            try:
                settings = json.loads((show_dir / "voice" / "VOICE.json").read_text())
            except json.JSONDecodeError:
                settings = {}
        reference = (show_dir / "voice" / "reference" / "prompt.wav") if kind == "owner_clone" else None

        async def speak(args):
            dec = self._check(emp, task_id, "voice.synthesize", {"voice": kind, "cost_usd": 0.0})
            if not dec.allowed:
                return err(f"denied by policy: {dec.reason}")
            if kind == "owner_clone" and not (show_dir / "voice" / "reference" / "CONSENT.md").exists():
                return err("the owner's consent record (voice/reference/CONSENT.md) is missing — return blocked and ask")
            out = inside(str(args.get("out", "")))
            if out is None or out.suffix.lower() != ".wav":
                return err("out must be a .wav path inside your project")
            ok_, msg = runtime.synthesize(str(args.get("text", "")), engine, voice_id, out, reference, settings)
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="voice",
                                  detail={"engine": engine, "voice": kind, "ok": ok_, "note": msg[:200]}))
                db.commit()
            return ok(f"wrote {out.relative_to(project)} ({msg})") if ok_ else err(msg + " — return blocked and tell the owner")
        return ToolSpec("voice_line", f"Speak one line in this show's voice ({engine}{' ' + voice_id if voice_id else ''}) "
                        "into a .wav in your project. [pause N] adds a pause.",
                        {"type": "object", "properties": {"text": {"type": "string"}, "out": {"type": "string"}},
                         "required": ["text", "out"]}, speak)

    def _act_tool(self, emp: Employee, task_id: str) -> ToolSpec:
        """Generic connector action. R2/R3 never execute here: they must go in pending_actions."""
        internal = set(TOOL_ACTIONS.values()) | {"web.search", "web.fetch", "cos.request", "delegate"}

        async def act(args):
            action, params = str(args.get("action")), dict(args.get("params") or {})
            if action in internal or action.startswith(("workspace.", "memory.", "slack.")):
                return err(f"'{action}' isn't a business tool — use the dedicated tool for it (C27)")
            dec = self._check(emp, task_id, action, params)
            if dec.outcome == APPROVAL:
                return err(f"'{action}' needs owner approval ({dec.tier}: {dec.reason}). Don't retry — add it to "
                           "pending_actions in your return packet with an exact preview.")
            if not dec.allowed:
                return err(f"denied: {dec.reason}")
            return err(f"'{action}' is permitted but no connector is configured for it yet. Say so in open_questions "
                       "and do not invent its result.")
        return ToolSpec("act", "Use a business tool from your allowlist, e.g. {action:'crm.read', params:{...}}.",
                        {"type": "object", "properties": {"action": {"type": "string"}, "params": {"type": "object"}},
                         "required": ["action"]}, act)

    def _submit_return_tool(self, emp: Employee, task_id: str, pt: str, sink: dict, ctx: dict) -> ToolSpec:
        prefix = f"{pt}-"

        async def handler(args):
            rp = {"task_id": task_id, "from": emp.id, **normalize_ids(args)}
            rp.setdefault("self_check", [])
            rp.setdefault("confidence", 0.5)
            rp.setdefault("outputs", [])
            if rp.get("status") not in ("done", "partial", "blocked", "out_of_scope"):
                return err("status must be done, partial, blocked or out_of_scope")
            names = [str(o).split("/")[-1] for o in rp["outputs"]]
            if not all(str(o).startswith("artifact://") for o in rp["outputs"]):
                return err("outputs must be artifact:// refs")
            if any(not n.startswith(prefix) for n in names):
                return err(f"outputs must be your own artifacts ({prefix}*) — never another employee's")
            missing = [n for n in names if not (task_dir(task_id) / "artifacts" / n).exists()]
            if missing:
                return err(f"outputs not found (write them first): {missing}")
            if rp["status"] in ("done", "partial") and not names:
                return err("a done/partial return needs at least one output artifact")
            with self.Session() as db:
                approved_tiers = set(db.get(Task, task_id).contract.get("planned_actions_tiers") or [])
            bad = validate_pending_actions(self.cfg, emp, rp.get("pending_actions") or [], approved_tiers)
            if bad:
                return err("pending_actions rejected: " + "; ".join(bad))
            unknown = self._unobserved_citations(task_id, rp.get("citations") or [], pt)
            if unknown:   # C44: fix citations in-session instead of burning a harness attempt
                return err(f"These citations weren't observed in this task: {unknown}. Use only owner:request, contract, "
                           f"handoff:{pt}, artifact:// refs you read, memory:<id> you read, or URLs you fetched — or drop "
                           "the claim.")
            shape = return_packet_problems({**rp, "memory_candidates": []})
            if shape:   # L1: fix the form now, in this session, instead of burning a harness attempt
                return err("Return packet malformed: " + shape + ". Fix it and call submit_return again.")
            with self.Session() as db:
                t = db.get(Task, task_id)
                for mc in rp.get("memory_candidates") or []:
                    mc = mc if isinstance(mc, dict) else {"content": str(mc)}
                    if mc.get("content"):
                        self.memory.submit_candidate(db, emp, t, mc["content"], kind=mc.get("kind") or "feedback",
                                                     layer=mc.get("layer") if mc.get("layer") in ("L1", "L3") else "L3",
                                                     pointer=mc.get("pointer"),
                                                     derived_from_untrusted=bool(ctx.get("untrusted")))
                db.commit()
            rp["memory_candidates"] = []  # stored as typed rows
            sink["return"] = rp
            return ok("Return packet stored. Stop here.")
        schema = {"type": "object", "properties": {
            "status": {"type": "string", "enum": ["done", "partial", "blocked", "out_of_scope"]},
            "outputs": {"type": "array", "items": {"type": "string"}}, "summary": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "object", "properties": {
                "claim": {"type": "string"}, "source": {"type": "string"}}, "required": ["claim", "source"]}},
            "self_check": {"type": "array", "items": {"type": "object", "properties": {
                "criterion_id": {"type": "string"}, "result": {"type": "string", "enum": ["met", "not_met", "unverifiable"]},
                "evidence": {"type": "string"}}, "required": ["criterion_id", "result", "evidence"]}},
            "confidence": {"type": "number"}, "open_questions": {"type": "array", "items": {"type": "string"}},
            "pending_actions": {"type": "array", "items": {"type": "object"}},
            "memory_candidates": {"type": "array", "items": {"type": "object"}}},
            "required": ["status", "outputs", "self_check", "confidence"]}
        return ToolSpec("submit_return", "Submit your return packet (once). Use status blocked + open_questions "
                        "instead of guessing.", schema, handler)

    # ================================================================== verify (LLM Verifier, §7)
    def _text_artifacts(self, task_id: str) -> list[tuple[str, str]]:
        art = task_dir(task_id) / "artifacts"
        return [(p.name, p.read_text(errors="replace")) for p in sorted(art.glob("*"))
                if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES and not p.name.startswith("X-")]

    def _returns(self, task_id: str) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(task_dir(task_id).glob("T*/return.json"))]

    def _source_text(self, task_id: str, srcs: list[str]) -> str:
        """Text of the task-internal sources a claim cites (owner request, contract, handoffs, artifacts, owner facts)."""
        with self.Session() as db:
            t = db.get(Task, task_id)
            owner, contract, plan = self._owner_text(t), json.dumps(t.contract or {}), list(t.plan or [])
        out = []
        for src in srcs:
            if src == "owner:request":
                out.append(owner)
            elif src == "contract":
                out.append(contract)
            elif re.fullmatch(r"handoff:T\d+", src) and int(src[9:]) <= len(plan):
                out.append(json.dumps(plan[int(src[9:]) - 1]))
            elif src.startswith("context:") and src[8:] in self.cfg.employees:
                out.append(self.cfg.owner_facts(src[8:]))
            elif src.startswith("artifact://"):
                p = task_dir(task_id) / "artifacts" / src.split("/")[-1]
                out.append(p.read_text(errors="replace") if p.exists() else "")
            elif src.startswith("memory:"):
                with self.Session() as db:
                    m = db.get(MemoryEntry, src[7:])
                    out.append(m.content if m else "")
            elif src.startswith("pipeline:"):
                from .db import PipelineItem
                with self.Session() as db:
                    r = db.get(PipelineItem, src[9:])
                    out.append(f"{r.to} {r.subject} {r.body} {r.note}" if r else "")
            elif src.startswith("upload:"):
                from . import uploads
                scope, _, name = src[7:].partition("/")
                p = uploads.path(scope, name)
                out.append(p.read_bytes()[:200_000].decode("utf-8", "replace") if p else "")
            elif src.startswith("email:") and self.email_reader.configured():
                try:
                    out.append(json.dumps(self.email_reader.open(src[6:])))
                except Exception:  # noqa: BLE001
                    out.append("")
        return "\n".join(out)

    def _needs_proof(self, t: Task) -> tuple[bool, str]:
        """Proof (fact checker) runs before Vera whenever a deliverable could state a fact (P5/P6)."""
        if not self._text_artifacts(t.id):
            return False, "no text deliverable"
        if any(r.get("citations") for r in self._returns(t.id)):
            return True, "cites sources"
        for name, text in self._text_artifacts(t.id):
            if Path(name).suffix.lower() in PROSE_SUFFIXES and CLAIM.search(URL.sub(" ", text)):
                return True, f"{name} contains numbers/dates/prices"   # C10
        if t.size in ("M", "L"):
            return True, f"size {t.size}"
        if any(self.cfg.employees[h["to"]].dept == "sales" for h in t.plan or []):
            return True, "research/writing work (pitches, applications, scripts) always gets its facts checked"
        return False, "short internal text, no factual claims"

    def _needs_llm_verifier(self, t: Task) -> tuple[bool, str]:
        """DECIDED (owner): Vera grades the brief only when you ask ('verify'), or while a new hire is on
        probation. Facts are always checked by Proof; external actions always wait for your G3 click."""
        if VERIFY.search(self._owner_text(t)) or t.contract.get("_verify_requested"):
            return True, "you asked to verify"
        if any(self.cfg.employees[h["to"]].probation for h in t.plan or [] if h.get("to") in self.cfg.employees):
            return True, "a new hire on probation worked on it"
        return False, "not requested (reply 'verify' to have Vera grade it against your brief)"

    def _to_revision(self, db, t: Task, actor: str, notes: str) -> bool:
        """Shared revision step for Proof and Vera findings. False = limit reached (escalated)."""
        t.revisions += 1
        if t.revisions > self.revision_limit:
            states.transition(db, t, "ESCALATED", actor, "revision limit reached")
            return False
        states.transition(db, t, "REVISION", actor)
        c2 = dict(t.contract)
        c2["_revision_notes"] = notes   # C46: specialists see the findings verbatim
        t.contract = c2
        return True

    async def factcheck(self, task_id: str) -> str | None:
        """Proof: claim-by-claim TRUE/FALSE/UNSOURCED. Returns revision notes, 'stop', or None (passed)."""
        with self.Session() as db:
            t = db.get(Task, task_id)
            plan_emps = [self.cfg.employees[h["to"]] for h in t.plan or []]
            # a deliverable built from private data (CV, statements) is never taken onto the web (exfiltration)
            offline = t.contains_pii or any(set(e.tools) & self.cfg.private_data_tools for e in plan_emps)
            contract = {k: v for k, v in t.contract.items() if not k.startswith("_")}
            db.commit()
        proof = self.cfg.employee("fact_checker")
        arts = [untrusted("deliverable", n, txt[:30_000]) for n, txt in self._text_artifacts(task_id)]
        cites = [c for r in self._returns(task_id) for c in r.get("citations", [])]
        required = set()
        prose = " ".join(_norm(txt) for name, txt in self._text_artifacts(task_id)
                         if Path(name).suffix.lower() in PROSE_SUFFIXES)
        for name, txt in self._text_artifacts(task_id):
            if Path(name).suffix.lower() in PROSE_SUFFIXES:
                txt = URL.sub(" ", txt)   # numbers inside links aren't claims
                spans = [m.span() for m in CLAIM.finditer(txt)]
                required |= {n.group(0) for n in NUMBER.finditer(txt)
                             if any(a < n.end() and n.start() < b for a, b in spans)}   # whole number, e.g. $49 -> 49
        prompt = ("Contract (a SOURCE you may cite as 'contract' — not a checklist; Vera grades the brief):\n"
                  + json.dumps(contract, indent=1) + "\n\nDeliverables:\n" + "\n\n".join(arts) +
                  "\n\nCitations the writers gave:\n" + json.dumps(cites, indent=1) +
                  "".join("\n\n" + owner_request(f"context:{e.id}", f"Owner facts (true — the owner's own words):\n{f}")
                          for e in plan_emps if (f := self.cfg.owner_facts(e.id))) +
                  ("\n\nThis task holds private data: do NOT use the web; check only against the cited task sources."
                   if offline else "\n\nRe-fetch cited URLs; for web facts find a second independent source."))
        sink: dict = {}

        async def submit_factcheck(args):
            claims = normalize_ids(args).get("claims")
            if not isinstance(claims, list):
                return err("claims must be a list of {claim, verdict, sources, evidence}")
            problems = []
            for i, c in enumerate(claims, 1):
                if not isinstance(c, dict) or not str(c.get("claim", "")).strip():
                    problems.append(f"#{i}: claim text missing")
                    continue
                if _norm(str(c.get("quote", ""))) not in prose or not _norm(str(c.get("quote", ""))):
                    problems.append(f"#{i}: quote must be copied word for word from the deliverable text — a claim is a "
                                    "fact stated IN the deliverable, not whether the brief was met (that is Vera's job)")
                    continue
                if c.get("verdict") not in ("TRUE", "FALSE", "UNSOURCED"):
                    problems.append(f"#{i}: verdict must be TRUE, FALSE or UNSOURCED")
                srcs = [str(x) for x in c.get("sources") or []]
                if c.get("verdict") == "TRUE" and not srcs:
                    problems.append(f"#{i}: TRUE needs the source(s) you checked it against")
                bad = self._unobserved_citations(task_id, srcs)
                if bad:
                    problems.append(f"#{i}: sources not observed in this task {bad} — fetch them or mark UNSOURCED")
                elif c.get("verdict") == "TRUE" and srcs and not any(x.startswith("http") for x in srcs):
                    missing = [n for n in NUMBER.findall(str(c.get("quote", "")) + " " + str(c["claim"]))
                               if n not in self._source_text(task_id, srcs)]
                    if missing:   # deterministic: the number must literally be in the task source it cites
                        problems.append(f"#{i}: {missing} not found in {srcs} — FALSE or UNSOURCED, not TRUE")
            covered = {n for c in claims if isinstance(c, dict)
                       for n in NUMBER.findall(str(c.get("quote", "")) + " " + str(c.get("claim", "")))}
            skipped = sorted(required - covered)
            if skipped:   # a lazy "no claims" can't pass while the deliverable states numbers
                problems.append(f"the deliverables state {skipped} but no claim covers them — list every factual claim")
            if problems:
                return err("Fact check rejected: " + "; ".join(problems[:8]))
            sink["claims"] = claims
            return ok("Fact check stored. Stop here.")
        tools = [ToolSpec("submit_factcheck", "Submit the claim-by-claim fact check (once).",
                          {"type": "object", "properties": {"claims": {"type": "array", "items": {"type": "object", "properties": {
                              "quote": {"type": "string", "description": "exact words copied from the deliverable"},
                              "claim": {"type": "string"}, "verdict": {"type": "string", "enum": ["TRUE", "FALSE", "UNSOURCED"]},
                              "sources": {"type": "array", "items": {"type": "string"}}, "evidence": {"type": "string"}},
                              "required": ["quote", "claim", "verdict", "sources", "evidence"]}}}, "required": ["claims"]},
                          submit_factcheck)]
        owner = self.task_owner(self._dept(task_id))
        self.live.handoff(task_id, owner, proof.id, "for_factcheck", contract.get("objective", ""))
        await self._run(proof, task_id, "factcheck", system_prompt(self.cfg, proof, "factcheck"), prompt, tools,
                        no_web=offline)
        if "claims" in sink:
            n_bad = sum(1 for x in sink["claims"] if x.get("verdict") != "TRUE")
            self.live.handoff(task_id, proof.id, owner, "factcheck_result",
                              "all facts check out" if not n_bad else f"{n_bad} claims wrong or unsourced", passed=not n_bad)
        with self.Session() as db:
            t = db.get(Task, task_id)
            if "claims" not in sink:
                states.transition(db, t, "ESCALATED", "fact_checker", "fact checker produced no result")
                db.commit()
                self._post(t, proof, "⚠️ I couldn't complete the fact check — escalating. Reply 'resume' to retry.")
                return "stop"
            c = dict(t.contract)
            c["_factcheck"] = sink["claims"]
            t.contract = c
            bad = [x for x in sink["claims"] if x["verdict"] != "TRUE"]
            if not bad:
                db.commit()
                return None
            notes = json.dumps({"fact_check_failed": bad})[:3000]
            if not self._to_revision(db, t, "fact_checker", notes):
                db.commit()
                self._post(t, proof, "⚠️ Facts still wrong or unsourced after 2 revisions — escalating to you.\n"
                           + json.dumps(bad)[:1500])
                return "stop"
            db.commit()
            return notes

    async def verify(self, task_id: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.transition(db, t, "VERIFYING", "harness", "all plan tasks passed automatic checks")
            need_proof, why_proof = self._needs_proof(t)
            need, why = self._needs_llm_verifier(t)
            db.add(AuditEvent(task_id=t.id, actor="dispatcher", kind="verifier_decision",
                              detail={"proof": need_proof, "proof_why": why_proof, "need": need, "why": why}))
            if not need:
                t.verification_id = f"auto-checks-{t.id}-v{t.contract_version}-r{t.revisions}"
            contract = {k: v for k, v in t.contract.items() if not k.startswith("_")}
            db.commit()
        self._active.add(task_id)   # the sweep must not mark Proof/Vera/the delivery note as stalled
        try:
            notes = await self.factcheck(task_id) if need_proof else None
            if notes is None and need:
                notes = await self._vera(task_id, contract)
            if not notes:
                await self.deliver(task_id)
        finally:
            self._active.discard(task_id)
        if notes and notes != "stop":
            await self.plan(task_id, revision_notes=notes)

    async def verify_on_request(self, task_id: str, user: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            for a in db.scalars(select(Approval).where(Approval.task_id == t.id, Approval.gate == "G4",
                                                       Approval.status == "pending")):
                a.status = "expired"   # a fresh G4 card follows Vera's grades
            c = dict(t.contract)
            c["_verify_requested"] = True
            t.contract = c
            states.transition(db, t, "VERIFYING", user, "owner asked to verify")
            contract = {k: v for k, v in t.contract.items() if not k.startswith("_")}
            db.commit()
        self._active.add(task_id)
        try:
            notes = await self._vera(task_id, contract)
        finally:
            self._active.discard(task_id)
        if notes == "stop":
            return
        if notes:
            await self.plan(task_id, revision_notes=notes)
            return
        await self.deliver(task_id)

    async def _vera(self, task_id: str, contract: dict) -> str | None:
        vera = self.cfg.employee("verifier")
        arts = [untrusted("deliverable", n, txt[:30_000]) for n, txt in self._text_artifacts(task_id)]
        cites = [c for r in self._returns(task_id) for c in r.get("citations", [])]
        prompt = ("Contract:\n" + json.dumps(contract, indent=1) + "\n\nDeliverables:\n" + "\n\n".join(arts) +
                  "\n\nCited sources:\n" + json.dumps(cites, indent=1) +
                  "\n\nFacts were already checked by Proof; you grade only whether the brief was met.")
        sink: dict = {}

        async def submit_verdict(args):
            args = normalize_ids(args)
            grades = args.get("grades") or []
            ids = [c["id"] for c in contract["acceptance_criteria"]]
            if sorted(str(g.get("criterion_id")) for g in grades) != sorted(ids):
                return err(f"grade every criterion exactly once: {ids}")
            if any(g.get("result") not in ("PASS", "FAIL", "UNVERIFIABLE") for g in grades):
                return err("result must be PASS, FAIL or UNVERIFIABLE")
            taste = {c["id"] for c in contract["acceptance_criteria"] if c.get("check") == "owner_taste"}
            if any(g["criterion_id"] in taste and g["result"] != "UNVERIFIABLE" for g in grades):
                return err(f"criteria {sorted(taste)} are the owner's taste call — grade them UNVERIFIABLE (C26)")
            sink["verdict"] = args
            return ok("Verdict stored. Stop here.")
        tools = [ToolSpec("submit_verdict", "Submit criterion grades (once).",
                          {"type": "object", "properties": {"grades": {"type": "array", "items": {"type": "object", "properties": {
                              "criterion_id": {"type": "string"}, "result": {"type": "string", "enum": ["PASS", "FAIL", "UNVERIFIABLE"]},
                              "evidence": {"type": "string"}}, "required": ["criterion_id", "result", "evidence"]}}},
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
                self._post(t, vera, "⚠️ I couldn't complete verification — escalating. Reply 'resume' to retry.")
                return "stop"
            fails = [g for g in verdict["grades"] if g.get("result") == "FAIL"]
            c = dict(t.contract)
            c["_verification"] = verdict
            t.contract = c
            if fails:
                notes = json.dumps({"failed": fails})[:3000]
                if not self._to_revision(db, t, "verifier", notes):
                    db.commit()
                    self._post(t, vera, "⚠️ Still failing after 2 revisions — escalating to you.\n" + json.dumps(fails)[:1500])
                    return "stop"
                db.commit()
                return notes
            t.verification_id = f"ver_{uuid.uuid4().hex[:8]}"
            db.commit()
            return None

    def _dept(self, task_id: str) -> str:
        with self.Session() as db:
            return db.get(Task, task_id).department

    # ================================================================== deliver (G4)
    async def deliver(self, task_id: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            lead = self.cfg.employee(self.cfg.leads[t.department]) if t.department in self.cfg.leads else self.cfg.employee("chief_of_staff")
            report = (t.contract or {}).get("_verification")
            db.commit()
        summaries = []
        for p in sorted(task_dir(task_id).glob("T*/return.json")):
            r = json.loads(p.read_text())
            summaries.append(untrusted("return", p.parent.name, f"{r.get('from')}: {r.get('summary', '')}\n"
                                                                 f"outputs: {r.get('outputs')}\nopen_questions: {r.get('open_questions', [])}"))
        arts = [n for n, _ in self._text_artifacts(task_id)] + sorted(
            p.name for p in (task_dir(task_id) / "artifacts").glob("*") if p.suffix.lower() not in TEXT_SUFFIXES)
        sink: dict = {}

        async def submit_delivery(args):
            sink["note"] = str(args.get("note", ""))[:3000]
            return ok("Delivery stored. Stop here.")
        with self.Session() as db:
            fc = (db.get(Task, task_id).contract or {}).get("_factcheck")
        prompt = ("Describe only what these summaries and the Verifier report say (C12):\n" + "\n".join(summaries) +
                  f"\n\nVerifier report: {json.dumps(report or 'automatic checks only')[:3000]}"
                  + (f"\nFact check: {len(fc)} claim(s), all TRUE" if fc is not None else ""))
        await self._run(lead, task_id, "deliver", system_prompt(self.cfg, lead, "deliver"), prompt,
                        [ToolSpec("submit_delivery", "Submit the owner-facing delivery note (once).",
                                  {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}, submit_delivery)])
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.transition(db, t, "DELIVERED", lead.id)
            t.delivery = {"note": sink.get("note", "(no note)"), "artifacts": arts}
            cands = list(db.scalars(select(MemoryEntry).where(MemoryEntry.task_id == t.id, MemoryEntry.status == "candidate",
                                                              MemoryEntry.standing.is_(False))))
            a = Approval(id=_id("apr"), task_id=t.id, gate="G4", contract_version=t.contract_version, preview={"artifacts": arts})
            db.add(a)
            db.commit()
            for name, text in self._text_artifacts(task_id)[:5]:
                self._post(t, lead, f"*{name}*\n```{text[:2500]}```" + (" …(truncated)" if len(text) > 2500 else ""))
            grades = ""
            if report:
                by = {}
                for g in report["grades"]:
                    by.setdefault(g["result"], []).append(g["criterion_id"])
                grades = "*Verifier:* " + ", ".join(f"{k} {v}" for k, v in sorted(by.items()))
                if by.get("UNVERIFIABLE"):
                    grades += " — please check the UNVERIFIABLE ones yourself"
            fc = t.contract.get("_factcheck")
            if fc is not None:
                grades = (grades + "\n" if grades else "") + f"*Proof (facts):* {len(fc)} claim(s) checked, all TRUE"
            taste = [c["id"] for c in t.contract.get("acceptance_criteria", []) if c.get("check") == "owner_taste"
                     or (c.get("check") == "verifier" and not report)]   # not graded unless you said 'verify'
            if not report:
                grades = (grades + "\n" if grades else "") + "_Reply 'verify' to have Vera grade this against your brief._"
            body = (f"{t.delivery['note']}\n\n*Artifacts:* {', '.join(arts) or '-'}\n{grades or '*Verification:* automatic checks'}"
                    + (f"\n*Your call (taste):* criteria {taste}" if taste else "") + f"\n*Cost:* ${t.cost_usd:.2f}")
            ticks = [(m.id, ("⚠ " if m.derived_from_untrusted else "") + m.content) for m in cands]
            self._post(t, lead, "Delivered — please accept or reject", blocks=approval_blocks(
                "G4 · Accept delivery?", body, a.id, checkboxes=ticks or None))
            self.live.approval_requested(a.id, t.id, "G4", lead.id, "Accept delivery?", body, artifacts=arts,
                                         memory_candidates=[{"id": i, "text": x} for i, x in ticks])
            self.live.handoff(t.id, lead.id, OWNER, "delivery", t.delivery["note"], approval_id=a.id,
                              artifacts=arts, memory_candidates=[{"id": i, "text": x} for i, x in ticks])

    async def accept(self, task_id: str, user: str, ticks: list[str]) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.transition(db, t, "ACCEPTED", user)
            db.flush()
            for m in db.scalars(select(MemoryEntry).where(MemoryEntry.task_id == t.id, MemoryEntry.status == "candidate",
                                                          MemoryEntry.standing.is_(False))):
                self.memory.promote(db, m.id, t, owner_ticked=m.id in ticks)
            pending = []
            for p in sorted(task_dir(task_id).glob("T*/return.json")):
                r = json.loads(p.read_text())
                for pa in r.get("pending_actions") or []:
                    pending.append((r["from"], pa))
            g3 = []
            for emp_id, pa in pending:
                action, params = str(pa.get("action")), dict(pa.get("params") or {})
                tier = self.cfg.action_tier(action)
                a = Approval(id=_id("apr"), task_id=t.id, gate="G3", tier=tier, action=action,
                             action_hash=action_hash(action, params), contract_version=t.contract_version,
                             preview={"employee": emp_id, "params": params, "preview": pa.get("preview")})
                db.add(a)
                g3.append(a)
            filed = self._file_proposals(t) if t.department == "talent" else []
            states.transition(db, t, "CLOSED", user)
            db.commit()
            if filed:
                self._post(t, None, "Hire proposal filed (NOT active): " + ", ".join(filed) + ". To hire: copy it into "
                           "config/org.yaml + skills.yaml + context/<id>.md, run scripts/validate_config.py, then give "
                           "it its 3 probation tasks.")
            for a in g3:
                body = f"*{a.preview['employee']}* wants to run `{a.action}` ({a.tier})\n```{json.dumps(a.preview, indent=1)[:2500]}```"
                self._post(t, None, f"Approval needed: {a.action}", blocks=approval_blocks(
                    f"G3 · {a.action}", body, a.id, action_hash=a.action_hash))
                self.live.approval_requested(a.id, t.id, "G3", a.preview["employee"], a.action, body, a.action_hash)
                try:
                    self.slack.post(self.slack.resolve_channel_id("#approvals"), f"G3 approval pending for task {t.id}: {a.action}")
                except Exception as e:  # noqa: BLE001
                    print(f"[workforce] #approvals mirror failed: {e}")
        if t.parent_id:
            self.live.handoff(task_id, self.task_owner(t.department), "chief_of_staff", "subtask_done", t.department,
                              parent_id=t.parent_id)
        await self._child_finished_if_any(task_id)

    def _file_proposals(self, t: Task) -> list[str]:
        """Talent: the Architect's accepted spec is copied to proposals/ — the live config is never touched."""
        out = []
        dest = self.cfg.dir.parent / "proposals"
        for h_i, h in enumerate(t.plan or [], 1):
            if h.get("task_type") != "design_employee":
                continue
            prim = plan_task_dir(t.id, f"T{h_i}") / "primary"
            if prim.exists():
                dest.mkdir(exist_ok=True)
                name = f"{t.id}-T{h_i}.yaml"
                shutil.copy(prim, dest / name)
                out.append(f"proposals/{name}")
        return out

    async def reject(self, task_id: str, user: str, reason: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            if t.status == "DELIVERED":
                states.transition(db, t, "REJECTED", user, reason)
            if not reason.strip():
                # C35: never let the Lead guess what the owner disliked
                db.commit()
                self._post(t, None, "Rejected. What should change? Reply in this thread — nothing is redone until you do.")
                return
            producers = {row.actor for row in db.scalars(select(AuditEvent).where(AuditEvent.task_id == t.id, AuditEvent.kind == "artifact"))}
            if reason:
                for pid in producers:
                    m = self.memory.submit_candidate(db, self.cfg.employee(pid), t, f"Owner rejected: {reason}", kind="feedback")
                    db.flush()
                    if self.memory.reject_reason(m) is None:   # C24: same rules as every candidate
                        m.status, m.verified_by = "active", user
                    else:
                        m.status = "rejected"
            states.transition(db, t, "REVISION", user)
            c2 = dict(t.contract)
            c2["_revision_notes"] = f"Owner rejected the delivery: {reason}"   # C46
            t.contract = c2
            t.revisions = 0  # a human rejection doesn't count toward the automatic revision limit (§5)
            db.commit()
        await self.plan(task_id, revision_notes=f"Owner rejected the delivery: {reason or '(no reason given — ask in open_questions)'}")

    async def _child_finished_if_any(self, task_id: str) -> None:
        with self.Session() as db:
            parent_id = db.get(Task, task_id).parent_id
        if parent_id:
            await self._child_finished(parent_id)

    async def _child_finished(self, parent_id: str) -> None:
        with self.Session() as db:
            p = db.get(Task, parent_id)
            kids = list(db.scalars(select(Task).where(Task.parent_id == parent_id)))
            if not kids or any(k.status not in states.TERMINAL for k in kids):
                return
            failed = [k for k in kids if k.status != "CLOSED"]
            if p.department == "hq":
                if p.status != "IN_PROGRESS":
                    return
                p.verification_id = f"children-{parent_id}"
                states.transition(db, p, "VERIFYING", "chief_of_staff")
                states.transition(db, p, "DELIVERED", "chief_of_staff")
                a = Approval(id=_id("apr"), task_id=p.id, gate="G4", contract_version=p.contract_version)
                db.add(a)
                db.commit()
                summary = "\n".join(f"• {k.department}: {k.status}" for k in kids)
                self._post(p, self.cfg.employee("chief_of_staff"), "All departments finished",
                           blocks=approval_blocks("G4 · Close cross-department task?", summary, a.id))
                self.live.approval_requested(a.id, p.id, "G4", "chief_of_staff", "Close cross-department task?", summary)
                self.live.handoff(p.id, "chief_of_staff", OWNER, "delivery", summary, approval_id=a.id)
                return
            if p.status != "WAITING_ON_DEPT":
                return
            if failed:
                states.transition(db, p, "ESCALATED", "chief_of_staff", "a department did not deliver")
                db.commit()
                self._post(p, self.cfg.employee("chief_of_staff"), "⚠️ " + ", ".join(f"{k.department} {k.status}" for k in failed)
                           + " — reply to redirect.")
                return
            refs, authors = [], {}
            dest = task_dir(p.id) / "artifacts"
            dest.mkdir(parents=True, exist_ok=True)
            for k in kids:
                for f in sorted((task_dir(k.id) / "artifacts").glob("*")):
                    if f.name.startswith("X-"):
                        continue
                    name = f"X-{k.department}-{f.name}"
                    shutil.copy(f, dest / name)
                    ref = f"artifact://{p.id}/{name}"
                    refs.append(ref)
                    m = re.match(r"T(\d+)-", f.name)   # who made it: the child's plan says (upstream_from check)
                    if m and int(m.group(1)) <= len(k.plan or []):
                        authors[ref] = (k.plan or [])[int(m.group(1)) - 1].get("to")
            c = dict(p.contract)
            c["_dept_inputs"] = refs
            c["_dept_input_authors"] = authors
            c.pop("_cross_pending", None)
            p.contract = c
            db.commit()
        await self.plan(parent_id)

    # ================================================================== G3 execution
    async def run_approved_action(self, approval_id: str) -> None:
        from .db import ActionRun
        with self.Session() as db:
            a = db.get(Approval, approval_id)
            t = db.get(Task, a.task_id)
            emp = self.cfg.employee(a.preview["employee"])
            params = dict(a.preview.get("params") or {})
            params["approval_id"] = a.id
            if db.scalar(select(ActionRun).where(ActionRun.task_id == t.id, ActionRun.action_hash == a.action_hash)):
                return  # idempotent: never twice
            dec = self.policy.check(db, emp, a.action, params, t)
            if dec.outcome != ALLOW:
                db.commit()
                self._post(t, None, f"Approved action `{a.action}` was blocked: {dec.reason}")
                return
            from . import connectors
            from .db import PipelineItem
            try:
                via, msg = connectors.execute(a.action, params)
                ok_ = via != "none"
            except Exception as e:  # noqa: BLE001 — a connector failure must not lose the approval record
                via, msg, ok_ = "error", f"{type(e).__name__}: {e}", False
            db.add(ActionRun(task_id=t.id, action_hash=a.action_hash, status="done" if ok_ else "failed",
                             result={"via": via, "detail": msg[:500]}))
            kind = PIPELINE_KIND.get((emp.id, a.action)) or PIPELINE_KIND.get(("*", a.action))
            if ok_ and kind:   # the pipeline is written by code from what was really sent — never by a model
                if any(h.get("task_type") == "follow_up" for h in t.plan or []) and kind == "pitch":
                    kind = "follow_up"
                now = datetime.now(timezone.utc)
                db.add(PipelineItem(id=_id("pl"), kind=kind, to=str(params.get("to") or params.get("company") or "")[:320],
                                    subject=str(params.get("subject") or params.get("role") or "")[:300],
                                    body=str(params.get("body") or params.get("cover_letter") or "")[:20_000],
                                    status="sent" if via == "smtp" else "ready_to_send", task_id=t.id, delivered_via=via,
                                    follow_up_due=now + timedelta(days=FOLLOW_UP_DAYS.get(kind, 7))))
            db.commit()
            self._post(t, emp, f"`{a.action}`: {msg}")

    # ================================================================== runner + budgets
    async def _run(self, emp: Employee, task_id: str, phase: str, system: str, prompt: str,
                   tools: list[ToolSpec], ctx: dict | None = None, no_web: bool = False) -> RunResult:
        with self.Session() as db:
            t = db.get(Task, task_id)
            paused = self.policy.paused(db, emp)
            cap = float(self.task_caps.get(t.size or "S", self.task_caps["S"]))
            month_left = self.monthly_budget - self.policy.counter_value(db, f"month:{_month()}", "plan", "llm_usd")
            remaining = max(0.0, min(cap - t.cost_usd, month_left))   # C38: one run can't overshoot the plan credit
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
                self._add_source(task_id, "urls", [params["url"]], (ctx or {}).get("pt"))
                if ctx is not None:
                    ctx["untrusted"] = True
            elif dec.allowed and ctx is not None:
                ctx["untrusted"] = True
            return dec.allowed, dec.reason

        guarded = [self._guard(emp, task_id, t) for t in tools]
        self.live.run_started(emp.id, task_id, phase)
        try:
            res = await self.runner.run(employee_id=emp.id, model=emp.model, phase=phase, system=system, prompt=prompt,
                                        tools=guarded, builtins=builtins, gate=gate, max_turns=30, budget_usd=remaining)
        except Exception as e:  # noqa: BLE001 — SDK/CLI failures must not crash the dispatcher
            res = RunResult(is_error=True, text=f"{type(e).__name__}: {e}")
        with self.Session() as db:
            t = db.get(Task, task_id)
            t.cost_usd += res.cost_usd
            spent = self.policy.bump(db, f"month:{_month()}", "plan", "llm_usd", res.cost_usd)
            db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="agent_run",
                              detail={"phase": phase, "cost": res.cost_usd, "error": res.is_error, "text": res.text[:300]}))
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

    # ================================================================== routines (owner-configured, on a clock)
    def due_routines(self, now: datetime | None = None) -> list[str]:
        """Routines whose local time has passed today and which haven't run today (owner_tz)."""
        from zoneinfo import ZoneInfo
        now = now or datetime.now(timezone.utc)
        local = now.astimezone(ZoneInfo(self.cfg.org.get("owner_tz", "UTC")))
        due = []
        for name, r in (self.cfg.org.get("routines") or {}).items():
            hh, mm = (int(x) for x in str(r["at"]).split(":"))
            if (local.hour, local.minute) >= (hh, mm):
                with self.Session() as db:
                    if not self.policy.counter_value(db, "system", f"routine:{name}", local.strftime("%Y-%m-%d")):
                        due.append(name)
        return due

    async def run_routine(self, name: str, now: datetime | None = None) -> str | None:
        """A routine is a fixed, owner-written plan (no model drafts it) at R1 at most: it can read and report,
        never send. It posts to the department channel and ends at your G4 like any task."""
        from zoneinfo import ZoneInfo
        r = (self.cfg.org.get("routines") or {})[name]
        now = now or datetime.now(timezone.utc)
        day = now.astimezone(ZoneInfo(self.cfg.org.get("owner_tz", "UTC"))).strftime("%Y-%m-%d")
        lead = self.cfg.employee(self.cfg.leads[r["department"]])
        with self.Session() as db:
            if self.policy.counter_value(db, "system", f"routine:{name}", day):
                return None
            self.policy.bump(db, "system", f"routine:{name}", day)
            db.commit()
        contract = {"objective": r["objective"], "size": "M" if len(r["handoffs"]) > 1 else "S",
                    "deliverables": [{"id": f"D{i}", "description": h["objective"], "assignee": h["to"], "task_type": h["task_type"]}
                                     for i, h in enumerate(r["handoffs"], 1)],
                    "acceptance_criteria": r["acceptance_criteria"], "planned_actions_tiers": []}
        handoffs = [{**h, "deliverable": f"D{i}"} for i, h in enumerate(r["handoffs"], 1)]
        channel = self.slack.resolve_channel_id(self.cfg.org["departments"][r["department"]]["channel"]) if self.slack else None
        with self.Session() as db:
            t = Task(id=_id("task"), department=r["department"], requested_by=f"routine:{name}",
                     original_request=r["objective"], slack_channel=channel, slack_thread=None)
            db.add(t)
            db.flush()
            states.new_contract_version(db, t, contract, "routine")
            t.size = contract["size"]
            states.transition(db, t, "CONTRACT_DRAFTED", "routine")
            t.g1_approval_id = f"routine-{name}-{day}"
            states.transition(db, t, "CONTRACT_APPROVED", "policy", "owner-configured routine")
            packets, problems = validate_plan(self.cfg, lead, t.id, contract, t.contract_version, t.size, handoffs,
                                              r["objective"], self.brand_kit, None)
            if problems:
                states.transition(db, t, "CANCELLED", "routine", "; ".join(problems))
                db.commit()
                print(f"[workforce] routine {name} is misconfigured: {problems}")
                return t.id
            t.plan = packets
            states.transition(db, t, "PLANNED", "routine")
            tid = t.id
            db.commit()
        await self.execute(tid)
        return tid

    # ================================================================== queue + routines (C41, C43)
    def _dept_busy(self, dept: str, exclude: str | None = None, show: str | None = None) -> bool:
        busy = ("CONTRACT_DRAFTED", "CONTRACT_APPROVED", "WAITING_ON_DEPT", "PLANNED", "IN_PROGRESS", "VERIFYING", "REVISION")
        with self.Session() as db:
            open_ = [t for t in db.scalars(select(Task).where(Task.status.in_(busy), Task.parent_id.is_(None)))
                     if t.id != exclude]
        if len([t for t in open_ if t.department == dept]) >= self.max_open:
            return True
        return bool(show) and len([t for t in open_ if t.show == show]) >= self.max_per_show   # I6

    async def drain_queue(self) -> list[str]:
        """Start queued tasks (oldest first) when their department has capacity."""
        started = []
        with self.Session() as db:
            queued = [(t.id, t.department, t.show) for t in db.scalars(
                select(Task).where(Task.status == "RECEIVED", Task.parent_id.is_(None)).order_by(Task.created_at))
                if not (t.contract or {}).get("_show_question")]
        for tid, dept, show in queued:
            if not self._dept_busy(dept, exclude=tid, show=show):
                await self.draft_contract(tid)
                started.append(tid)
        return started

    def digest(self, now: datetime | None = None) -> str | None:
        """Deterministic routine (no model, no credit): daily #hq digest; Friday per-department summary."""
        now = now or datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        with self.Session() as db:
            if self.policy.counter_value(db, "system", "digest", day):
                return None
            since = now - timedelta(days=1 if now.weekday() != 4 else 7)
            rows = [t for t in db.scalars(select(Task).where(Task.parent_id.is_(None)))
                    if _aware(t.updated_at) >= since]
            spent = self.policy.counter_value(db, f"month:{_month()}", "plan", "llm_usd")
            self.policy.bump(db, "system", "digest", day)
            db.commit()
        by: dict[str, list[str]] = {}
        for t in rows:
            by.setdefault(t.department, []).append(f"{t.status.lower()}: {(t.contract or {}).get('objective', t.original_request)[:60]}")
        lines = [f"*{d}* — " + "; ".join(v[:5]) for d, v in sorted(by.items())] or ["no activity"]
        text = (f"{'Weekly' if now.weekday() == 4 else 'Daily'} digest · plan credit ${spent:.2f}/${self.monthly_budget:.0f}\n"
                + "\n".join(lines))
        try:
            self.slack.post(self.slack.resolve_channel_id(self.cfg.org["core"]["chief_of_staff"]["channel"]), text,
                            persona={"name": self.cfg.employee("chief_of_staff").name, "icon_emoji": ":robot_face:"})
        except Exception as e:  # noqa: BLE001
            print(f"[workforce] digest post failed: {e}")
        return text

    # ================================================================== sweep (C21, C22)
    def sweep(self, boot: bool = False, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        rep = {"reminded": 0, "expired": 0, "interrupted": 0, "resumed_budget": False, "gc": False}
        pol = self.cfg.permissions["approval_policy"]
        reminders = [timedelta(hours=h) for h in pol["reminders_after_hours"]]
        park = timedelta(hours=pol["park_task_after_hours"])
        stall = timedelta(minutes=self.cfg.permissions["budgets_default"]["no_progress_escalate_min"])
        with self.Session() as db:
            for a in db.scalars(select(Approval).where(Approval.status.in_(["pending", "confirming"]))):
                t = db.get(Task, a.task_id)
                age = now - _aware(a.created_at)
                sent = int((a.preview or {}).get("_reminded", 0))
                if age >= park:
                    a.status = "expired"
                    self.live.approval_closed(a.id, "expired")
                    rep["expired"] += 1
                    self._post(t, None, f"⏸ {a.gate} approval parked after {pol['park_task_after_hours']}h with no answer "
                                        "(silence = no). Reply in this thread to revive.")
                elif sent < len(reminders) and age >= reminders[sent]:
                    a.preview = {**(a.preview or {}), "_reminded": sent + 1}
                    rep["reminded"] += 1
                    self._post(t, None, f"🔔 Reminder: {a.gate} approval waiting since {int(age.total_seconds() // 3600)}h.")
            for t in db.scalars(select(Task).where(Task.status.in_(IN_FLIGHT))):
                if t.id in self._active:
                    continue
                if t.status == "PLANNED" and db.scalar(select(Approval.id).where(
                        Approval.task_id == t.id, Approval.gate == "G2", Approval.status == "pending")):
                    continue  # legitimately waiting for the owner's plan approval
                resumes = int((t.contract or {}).get("_auto_resumes", 0))
                if boot and t.plan and t.status in ("PLANNED", "IN_PROGRESS", "REVISION") and resumes < 1:
                    c = dict(t.contract)
                    c["_auto_resumes"] = resumes + 1     # once per task: a crash loop must not burn credit
                    t.contract = c
                    rep.setdefault("resume", []).append(t.id)   # the app restarts the round (harness state is on disk)
                    continue
                if boot or now - _aware(t.updated_at) >= stall:
                    states.transition(db, t, "ESCALATED", "sweep", "interrupted (restart/crash) or stalled")
                    rep["interrupted"] += 1
                    self._post(t, None, "⚠️ This task was interrupted. Reply 'resume' to continue, or give new direction.")
            p = db.get(Pause, "all")
            if p and p.by == "budget" and not p.reason.startswith(f"budget:{now.strftime('%Y-%m')}"):
                self.policy.resume(db, "all", "sweep")
                rep["resumed_budget"] = True
            week = now.strftime("%G-W%V")
            if self.policy.counter_value(db, "system", "gc", week) == 0:
                self.memory.gc(db)
                self.policy.bump(db, "system", "gc", week)
                rep["gc"] = True
            db.commit()
        return rep

    # ================================================================== slack out
    def _post(self, t: Task, emp: Employee | None, text: str, blocks: list | None = None) -> None:
        persona = {"name": emp.name, "icon_emoji": ":robot_face:"} if emp else {"name": "Dispatcher", "icon_emoji": ":gear:"}
        self.live.said(t.id, emp.id if emp else None, text)
        try:
            self.slack.post(t.slack_channel or self.cfg.owner_id, text, t.slack_thread, persona, blocks)
        except Exception as e:  # noqa: BLE001 — Slack outage must not lose task state
            print(f"[workforce] slack post failed: {e}")

    # ================================================================== hiring (Talent -> you -> live)
    def hire(self, proposal: str) -> str:
        """You approved an Architect proposal: validate it again, add it to config/hires.yaml with probation on,
        write its training file, reload the org. Nothing else in the config is touched."""
        import yaml
        from .checks import employee_spec
        from .config import Config, get_config
        root = self.cfg.dir.parent
        CONTEXT_DIR = root / "context"
        src = (root / "proposals" / Path(proposal).name)
        if not src.is_file():
            return f"no proposal proposals/{Path(proposal).name}"
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = employee_spec(str(src))
        if code != 0:
            return f"Not hired — the spec no longer validates: {buf.getvalue().strip()}"
        spec = yaml.safe_load(src.read_text())
        hires_p = self.cfg.dir / "hires.yaml"
        hires = yaml.safe_load(hires_p.read_text()) if hires_p.exists() else {}
        hires = hires or {}
        hires.setdefault("employees", [])
        entry = {k: spec[k] for k in ("id", "name", "department", "does", "does_not", "tools", "max_tier", "personality")}
        entry.update({"probation": True, "routes": spec["routes"], "new_skills": spec.get("new_skills") or {}})
        hires["employees"].append(entry)
        hires_p.write_text("# Employees you hired via Talent (/wf hire). Same rules as org.yaml; probation = Vera grades their work.\n"
                           + yaml.safe_dump(hires, sort_keys=False))
        for name, text in (spec.get("new_skills") or {}).items():
            d = root / ".claude" / "skills" / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(str(text))
        CONTEXT_DIR.mkdir(exist_ok=True)
        (CONTEXT_DIR / f"{spec['id']}.md").write_text(
            f"# {spec['name']} — `{spec['id']}`\n\n## Role\n{spec['context']}\n\n## Fire when\n{spec['fire_when']}\n\n## Skills\n"
            + "\n".join(f"- `{r['task_type']}` — skills: {', '.join(r.get('run') or []) or 'none'} · checks: {', '.join(r['checks'])}"
                        for r in spec["routes"])
            + "\n\n## Never\n" + "\n".join(f"- {x}" for x in spec["does_not"])
            + "\n\n## Owner must provide\n- [ ] (from the proposal)\n\n## Owner facts\n_(empty)_\n")
        get_config.cache_clear()
        self.cfg = Config(self.cfg.dir)
        self.policy.cfg = self.memory.cfg = self.harness.cfg = self.cfg
        self.policy.p = self.cfg.permissions
        tasks = "\n".join(f"{i}. {t}" for i, t in enumerate(spec["probation_tasks"], 1))
        return (f"Hired {spec['name']} ({spec['id']}) into {spec['department']} on probation — Vera grades its work "
                f"until `/wf end-probation {spec['id']}`. Give it these 3 probation tasks in "
                f"{self.cfg.org['departments'][spec['department']]['channel']}:\n{tasks}")

    def end_probation(self, eid: str) -> str:
        import yaml
        from .config import Config, get_config
        p = self.cfg.dir / "hires.yaml"
        hires = yaml.safe_load(p.read_text()) if p.exists() else {}
        for e in (hires or {}).get("employees", []):
            if e["id"] == eid:
                e["probation"] = False
                p.write_text("# Employees you hired via Talent (/wf hire).\n" + yaml.safe_dump(hires, sort_keys=False))
                get_config.cache_clear()
                self.cfg = Config(self.cfg.dir)
                self.policy.cfg = self.memory.cfg = self.harness.cfg = self.cfg
                return f"{eid} is off probation."
        return f"{eid} isn't a hire on probation."

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


# ====================================================================== validation (pure functions)
_ID_LISTS = ("criteria", "inputs_from")


CHITCHAT = re.compile(r"^\W*(thanks|thank you|thx|ok|okay|cool|nice|great|lol|haha|yes|no|👍|🙏)\W*$", re.I)


def is_chitchat(text: str) -> bool:
    """C40: acknowledgements aren't work requests (they'd otherwise start a paid task)."""
    t = (text or "").strip()
    return bool(CHITCHAT.match(t)) or len(re.findall(r"\w+", t)) < 2


def normalize_ids(obj):
    """L2: models send ids as numbers (1) or strings ("1"); everything downstream compares strings."""
    if isinstance(obj, list):
        return [normalize_ids(x) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if k in ("id", "criterion_id", "deliverable") and isinstance(v, (int, float)):
            v = str(int(v)) if float(v).is_integer() else str(v)
        elif k in _ID_LISTS and isinstance(v, list):
            v = [str(int(x)) if isinstance(x, (int, float)) and float(x).is_integer() else x for x in v]
        else:
            v = normalize_ids(v)
        out[k] = v
    return out


def return_packet_problems(rp: dict) -> str:
    import jsonschema
    from .checks import _return_schema
    try:
        jsonschema.validate(rp, _return_schema())
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "packet"
        return f"{where}: {e.message}"
    return ""
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
