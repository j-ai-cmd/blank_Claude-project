"""Tool Proxy policy engine: every tool call from every employee passes through `check`.

Deny by default. Implements permissions.yaml: allowlists, tiers, restricted kinds, private-data vs
egress split, bulk windows (per task and per employee per day), spend caps, kill switches, and
hash-bound approvals for R2/R3.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import TIER, Config, Employee
from .db import Approval, AuditEvent, Counter, Pause, Task

ALLOW, APPROVAL, DENY = "allow", "approval", "deny"

# action -> bulk metric name in permissions.yaml
BULK_METRIC = {
    "crm.update_record": "crm_records_updated",
    "calendar.hold_internal": "calendar_events_created",
    "drive.create_draft": "files_created",
    "workspace.write": "files_created",
    "slack.post_own_thread": "slack_messages_posted",
    "slack.post_own_channel": "slack_messages_posted",
    "email.send_external": "emails_sent_external",
}
PAID_ACTIONS = {"image.generate", "image.edit", "video.render", "enrichment.lookup", "sandbox.exec", "voice.synthesize"}


@dataclass
class Decision:
    outcome: str
    tier: str
    reason: str
    action_hash: str

    @property
    def allowed(self) -> bool:
        return self.outcome == ALLOW


def action_hash(action: str, params: dict) -> str:
    clean = {k: v for k, v in (params or {}).items() if k not in ("approval_id", "_meta")}
    blob = json.dumps({"action": action, "params": clean}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Policy:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.p = cfg.permissions

    # ------------------------------------------------------------------ counters
    def _counter(self, db: Session, scope: str, key: str, metric: str) -> Counter:
        c = db.scalar(select(Counter).where(Counter.scope == scope, Counter.key == key, Counter.metric == metric))
        if c is None:
            c = Counter(scope=scope, key=key, metric=metric, value=0)
            db.add(c)
            db.flush()
        return c

    def counter_value(self, db: Session, scope: str, key: str, metric: str) -> float:
        c = db.scalar(select(Counter).where(Counter.scope == scope, Counter.key == key, Counter.metric == metric))
        return c.value if c else 0.0

    def bump(self, db: Session, scope: str, key: str, metric: str, by: float = 1) -> float:
        c = self._counter(db, scope, key, metric)
        c.value += by
        return c.value

    # ------------------------------------------------------------------ pauses
    def paused(self, db: Session, emp: Employee) -> str | None:
        scopes = ["all", f"emp:{emp.id}"] + ([f"dept:{emp.dept}"] if emp.dept else [])
        for s in scopes:
            p = db.get(Pause, s)
            if p:
                return f"paused ({s}): {p.reason}"
        return None

    def pause(self, db: Session, scope: str, reason: str, by: str) -> None:
        if not db.get(Pause, scope):
            db.add(Pause(scope=scope, reason=reason, by=by))
            db.flush()
        self._audit(db, None, by, "pause", {"scope": scope, "reason": reason})

    def resume(self, db: Session, scope: str, by: str) -> None:
        p = db.get(Pause, scope)
        if p:
            db.delete(p)
            db.flush()
        self._audit(db, None, by, "resume", {"scope": scope})

    # ------------------------------------------------------------------ main check
    def check(self, db: Session, emp: Employee, action: str, params: dict | None = None,
              task: Task | None = None) -> Decision:
        params = params or {}
        h = action_hash(action, params)
        tier = self.cfg.action_tier(action)

        def done(outcome: str, t: str, reason: str) -> Decision:
            d = Decision(outcome, t, reason, h)
            self._audit(db, task.id if task else None, emp.id, "tool_check",
                        {"action": action, "outcome": outcome, "tier": t, "reason": reason, "hash": h})
            return d

        why = self.paused(db, emp)
        if why:
            return done(DENY, tier or "?", why)
        if tier is None:
            return done(DENY, "?", "unknown action (deny by default)")
        if tier == "R4":
            self._violation(db, emp, task, action, "R4 forbidden action")
            return done(DENY, tier, "forbidden (R4)")
        if action not in emp.tools:
            return done(DENY, tier, "tool not in this employee's allowlist")
        rk = self.cfg.restricted_kind(action)
        if rk and rk != emp.kind:
            return done(DENY, tier, f"action restricted to kind '{rk}'")
        if TIER[tier] > emp.max_tier_level:
            return done(DENY, tier, f"{tier} exceeds max_tier {emp.max_tier}")

        if action == "voice.synthesize":
            allowed_voices = self.allowed_voices(emp)
            if params.get("voice") not in allowed_voices:
                return done(DENY, tier, f"voice '{params.get('voice')}' not allowed for {emp.id}; "
                                        f"allowed: {sorted(allowed_voices) or 'none'} (I5)")

        if action == "web.fetch":
            reason = self._egress(db, emp, params, task)
            if reason:
                return done(DENY, tier, reason)

        eff = tier
        bump_reason = self._bulk_exceeded(db, emp, action, params, task)
        if bump_reason and TIER[eff] < TIER["R2"]:
            eff = "R2"
        spend_reason = None
        if action in PAID_ACTIONS:
            spend_reason, hard = self._spend(db, emp, params)
            if hard:
                self.pause(db, f"emp:{emp.id}", "spend >= 150% of daily cap", "policy")
                return done(DENY, tier, "daily spend runaway guard (150%) — employee paused")
            if spend_reason and TIER[eff] < TIER["R2"]:
                eff = "R2"

        if TIER[eff] >= TIER["R2"]:
            ok, reason = self._consume_approval(db, params.get("approval_id"), h, eff, task)
            if not ok:
                return done(APPROVAL, eff, reason if params.get("approval_id") else
                            (bump_reason or spend_reason or f"{eff} requires approval"))
        self._record_use(db, emp, action, params, task)
        return done(ALLOW, eff, "ok")

    def allowed_voices(self, emp: Employee) -> set[str]:
        """I5: the owner's cloned voice belongs to the Jai show only; everyone else gets base voices."""
        if emp.show:
            v = (self.cfg.shows.get(emp.show) or {}).get("voice", "none")
            return set() if v == "none" else {v}
        return {"base"}

    # ------------------------------------------------------------------ helpers
    def _violation(self, db: Session, emp: Employee, task: Task | None, action: str, why: str) -> None:
        n = self.bump(db, f"emp:{emp.id}", "violations", "r4_attempts")
        self._audit(db, task.id if task else None, emp.id, "violation", {"action": action, "why": why, "count": n})
        limit = self.p["kill_switches"]["auto_pause"]["r4_attempts"]
        if n >= limit:
            self.pause(db, f"emp:{emp.id}", f"{int(n)} forbidden-action attempts", "policy")

    def _egress(self, db: Session, emp: Employee, params: dict, task: Task | None) -> str | None:
        url = str(params.get("url", ""))
        holds_private = bool(set(emp.tools) & self.cfg.private_data_tools)
        constraint = emp.tool_constraints.get("web.fetch")
        if holds_private and not constraint:
            return "employees holding private data may not fetch the web"
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "invalid URL"
        block = self.p["egress"]["block_if"]
        if len(parsed.query) > block["query_string_chars_over"]:
            return "query string too long (exfiltration guard)"
        host = parsed.hostname
        if block.get("ip_literal_or_localhost"):
            if host in ("localhost",) or host.endswith(".local"):
                return "localhost blocked"
            try:
                ipaddress.ip_address(host)
                return "IP-literal URLs blocked"
            except ValueError:
                pass
        if task is not None and block.get("url_contains_private_task_data"):
            for s in (task.contract or {}).get("_private_strings", []):
                if s and s.lower() in url.lower():
                    return "URL contains private task data"
        if constraint and constraint.get("mode") == "exact_urls_in_task_fetch_log_only":
            if task is None or url not in self.fetch_log(db, task.id):
                return "verifier may only re-fetch URLs already in the task fetch log"
        return None

    def fetch_log(self, db: Session, task_id: str) -> set[str]:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.task_id == task_id, AuditEvent.kind == "fetched"))
        return {r.detail.get("url") for r in rows}

    def _bulk_exceeded(self, db: Session, emp: Employee, action: str, params: dict, task: Task | None) -> str | None:
        metric = BULK_METRIC.get(action)
        if not metric:
            return None
        n = float(params.get("count", 1))
        bt = self.p["bulk_thresholds"]
        if task is not None:
            lim = bt["per_task"].get(metric)
            if lim is not None and self.counter_value(db, f"task:{task.id}", emp.id, metric) + n > lim:
                return f"bulk: {metric} over per-task limit {lim}"
        lim = bt["per_employee_per_day"].get(metric)
        if lim is not None and self.counter_value(db, f"emp:{emp.id}:{today()}", emp.id, metric) + n > lim:
            return f"bulk: {metric} over daily limit {lim}"
        return None

    def spend_cap(self, emp: Employee) -> float:
        caps = self.p["spend_caps_usd_per_employee_per_day"]
        return float(caps.get(emp.id, caps["default"]))

    def _spend(self, db: Session, emp: Employee, params: dict) -> tuple[str | None, bool]:
        cost = float(params.get("est_cost_usd", 0))
        spent = self.counter_value(db, f"emp:{emp.id}:{today()}", emp.id, "spend_usd")
        cap = self.spend_cap(emp)
        hard_pct = self.p["kill_switches"]["auto_pause"]["spend_pct_of_daily_cap"] / 100
        if spent + cost >= cap * hard_pct:
            return "spend runaway", True
        if spent + cost >= cap:
            return f"daily spend cap ${cap:.2f} reached", False
        return None, False

    def _record_use(self, db: Session, emp: Employee, action: str, params: dict, task: Task | None) -> None:
        metric = BULK_METRIC.get(action)
        n = float(params.get("count", 1))
        if metric:
            self.bump(db, f"emp:{emp.id}:{today()}", emp.id, metric, n)
            if task is not None:
                self.bump(db, f"task:{task.id}", emp.id, metric, n)
        if action in PAID_ACTIONS and params.get("est_cost_usd"):
            self.bump(db, f"emp:{emp.id}:{today()}", emp.id, "spend_usd", float(params["est_cost_usd"]))

    def _consume_approval(self, db: Session, approval_id: str | None, h: str, tier: str,
                          task: Task | None) -> tuple[bool, str]:
        if not approval_id:
            return False, "no approval"
        a = db.get(Approval, approval_id)
        if a is None or a.gate != "G3":
            return False, "unknown approval"
        if a.status != "approved":
            return False, f"approval is {a.status}"
        if a.action_hash != h:
            return False, "approval does not match this exact action (hash mismatch)"
        if TIER[a.tier or "R2"] < TIER[tier]:
            return False, "approval tier too low"
        if task is not None and (a.task_id != task.id or a.contract_version != task.contract_version):
            return False, "approval belongs to another task or contract version"
        a.status = "used"  # single_action: never replays
        return True, "approved"

    # ------------------------------------------------------------------ approvers
    def can_approve(self, user_id: str, tier: str, dept: str | None) -> bool:
        """tier 'OWNER' = G1/G2/G4/GM gates: owner only (owner decision: only the owner gives and accepts work)."""
        ap = self.p["approval_policy"]["approvers"]
        owner = set(ap.get("owner") or []) | {self.cfg.owner_id}
        if user_id in owner:
            return True
        if tier == "OWNER":
            return False
        if tier == "R3":
            return False  # away-mode delegation handled by AwayMode (not granted by default)
        if tier == "R2":
            managers = set((ap.get("dept_managers") or {}).get(dept or "", []) or [])
            backup = set(ap.get("backup") or [])
            return user_id in managers or user_id in backup
        return False

    def is_requester(self, user_id: str, dept: str | None) -> bool:
        req = self.p["requesters"]
        owners = set(req.get("owner") or []) | {self.cfg.owner_id}
        if user_id in owners:
            return True
        if req.get("owner_only"):
            return False
        return user_id in set((req.get("by_department") or {}).get(dept or "", []) or [])

    # ------------------------------------------------------------------ audit
    def _audit(self, db: Session, task_id: str | None, actor: str, kind: str, detail: dict) -> None:
        db.add(AuditEvent(task_id=task_id, actor=actor, kind=kind, detail=detail))
