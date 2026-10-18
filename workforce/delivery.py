"""Delivery, owner accept/reject (G4), child-task resume and approved actions (G3)."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from . import states
from .agents import ToolSpec, ok
from .db import Approval, AuditEvent, MemoryEntry, Task
from .dispatch_common import FOLLOW_UP_DAYS, PIPELINE_KIND, TEXT_SUFFIXES, _id
from .harness import plan_task_dir, task_dir
from .live import OWNER
from .policy import ALLOW, action_hash
from .prompts import system_prompt, untrusted
from .slack import approval_blocks


class DeliveryMixin:
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
