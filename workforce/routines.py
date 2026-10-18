"""Clock work: routines, queue drain, digest, sweep, and Talent hiring/probation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from . import states
from .contracts import validate_plan
from .db import Approval, Pause, Task
from .dispatch_common import IN_FLIGHT, _aware, _id, _month


class RoutinesMixin:
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
