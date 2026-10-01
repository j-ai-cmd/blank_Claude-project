"""Memory layers L1/L3 with row ACLs + Librarian promotion rules + GC (config/memory.yaml).

Agents never write shared memory: they submit candidates; only `promote` (Librarian path) activates them.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import Config, Employee
from .db import AuditEvent, MemoryEntry, Task
from .pii import find_pii

STOP = {"the", "and", "for", "from", "now", "always", "never", "our", "your", "with", "use", "all", "any", "this",
        "that", "are", "on", "every", "time", "going", "forward", "future", "default"}
INTENTION = re.compile(r"^\s*(i\s+will|i'll|we\s+will|plan\s+to|going\s+to|i\s+intend)\b", re.I)
SECRET = re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]\s*\S+|sk-[A-Za-z0-9]{16,}|xox[bap]-[A-Za-z0-9-]+", re.I)


class MemoryError_(Exception):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class MemoryStore:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    # ------------------------------------------------------------------ read (ACL)
    def readable_scopes(self, emp: Employee, show: str | None = None) -> list[tuple[str, str]]:
        if emp.kind in ("verifier", "fact_checker"):
            return []   # I7: auditors carry nothing from one task into the next
        scopes: list[tuple[str, str]] = [("L1", "hq")]   # C32: company-wide standing rules reach everyone
        show = emp.show or show
        if show:
            scopes.append(("L1", f"show:{show}"))        # I3: show rules reach only that show's task
        for grant in emp.memory_read:
            if grant == "L3_self":
                if show and not emp.show:
                    scopes.append(("L3", f"{emp.id}@{show}"))   # I4: on a show task a shared helper reads ONLY
                else:                                            # that show's memory, never its general memory
                    scopes.append(("L3", emp.id))
            elif grant.startswith("L1") and emp.dept:
                scopes += [("L1", emp.dept), ("L1_daily", emp.dept)]
            elif grant == "L1_all_depts_readonly" or grant == "L1_all":
                scopes += [("L1", d) for d in self.cfg.org["departments"]]
            elif grant == "L1_task_dept":
                pass  # resolved per task by caller
        return scopes

    def read(self, db: Session, emp: Employee, query: str = "", limit: int = 12,
             extra_scopes: list[tuple[str, str]] | None = None, show: str | None = None) -> list[MemoryEntry]:
        scopes = self.readable_scopes(emp, show) + (extra_scopes or [])
        if not scopes:
            return []
        cond = or_(*[(MemoryEntry.layer == l) & (MemoryEntry.scope_id == s) for l, s in scopes])
        rows = list(db.scalars(select(MemoryEntry).where(cond, MemoryEntry.status == "active")))
        words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 2}

        def score(m: MemoryEntry) -> float:
            rel = 1.0 + (len(words & set(re.findall(r"\w+", m.content.lower()))) if words else 0)
            age = (now() - (_aware(m.last_used_at) or _aware(m.created_at))).days
            return rel * (0.97 ** age) * (m.confidence or 0.5) + (5 if m.pinned else 0)

        if words:   # minimal context: only memory that shares a word with the task, plus pinned/standing rules
            rows = [m for m in rows if m.pinned or m.standing
                    or words & set(re.findall(r"\w+", m.content.lower()))]
        rows.sort(key=score, reverse=True)
        picked = rows[:limit]
        for m in picked:
            m.last_used_at = now()
        return picked

    # ------------------------------------------------------------------ candidates
    def submit_candidate(self, db: Session, emp: Employee, task: Task, content: str, kind: str = "feedback",
                         layer: str = "L3", source: str | None = None, pointer: str | None = None,
                         derived_from_untrusted: bool = False, standing: bool = False) -> MemoryEntry:
        show = emp.show or task.show
        if layer == "L3":
            scope = f"{emp.id}@{show}" if show and not emp.show else emp.id   # I4
        else:
            scope = f"show:{show}" if show else (emp.dept or task.department)   # I3: never the whole dept
        m = MemoryEntry(id=f"mem_{uuid.uuid4().hex[:12]}", layer=layer, scope_id=scope, kind=kind,
                        content=content[:1000], source=source or f"task:{task.id}", author=emp.id,
                        pointer=pointer, status="candidate", task_id=task.id, standing=standing,
                        derived_from_untrusted=derived_from_untrusted, confidence=0.7)
        db.add(m)
        return m

    def reject_reason(self, m: MemoryEntry) -> str | None:
        if not m.source:
            return "no source"
        if INTENTION.search(m.content):
            return "content is an intention, not an outcome"
        if SECRET.search(m.content):
            return "contains a secret"
        if find_pii(m.content):
            return "contains personal data (store a pointer instead)"
        if m.kind == "fact_pointer" and not m.pointer:
            return "fact must be stored as a pointer"
        return None

    def promote(self, db: Session, entry_id: str, task: Task | None, owner_ticked: bool,
                by: str = "librarian", owner_standing: bool = False, pinned: bool = False) -> MemoryEntry:
        m = db.get(MemoryEntry, entry_id)
        if m is None or m.status != "candidate":
            raise MemoryError_("not a candidate")
        why = self.reject_reason(m)
        allowed = ((task is not None and task.status in ("ACCEPTED", "CLOSED") and owner_ticked)
                   or owner_standing
                   or (m.kind == "fact_pointer" and m.pointer))
        if why or not allowed:
            m.status = "rejected"
            db.add(AuditEvent(task_id=m.task_id, actor=by, kind="memory_rejected",
                              detail={"id": m.id, "why": why or "promotion rule not met"}))
            return m
        # supersede older active entry on the same topic (same scope + kind + first tag)
        if m.supersedes:
            old = db.get(MemoryEntry, m.supersedes)
            if old and not old.pinned:
                old.status = "archived"
        m.status, m.verified_by, m.pinned = "active", by, pinned
        m.standing = m.standing or owner_standing
        if not pinned and m.standing:
            m.expires_at = now() + timedelta(days=int(self.cfg.memory["instruction_classification"]["standing"]["default_ttl_days"]))
        db.add(AuditEvent(task_id=m.task_id, actor=by, kind="memory_promoted", detail={"id": m.id, "layer": m.layer}))
        return m

    def same_topic(self, db: Session, m: MemoryEntry) -> MemoryEntry | None:
        """Active standing rule in the same scope whose wording overlaps >= 50% (Jaccard on content words)."""
        words = {w for w in re.findall(r"[a-z]{3,}", m.content.lower())} - STOP
        best, score = None, 0.0
        for o in db.scalars(select(MemoryEntry).where(MemoryEntry.layer == m.layer, MemoryEntry.scope_id == m.scope_id,
                                                      MemoryEntry.status == "active", MemoryEntry.standing.is_(True),
                                                      MemoryEntry.id != m.id)):
            ow = {w for w in re.findall(r"[a-z]{3,}", o.content.lower())} - STOP
            j = len(words & ow) / max(1, len(words | ow))
            if j > score:
                best, score = o, j
        return best if score >= 0.5 else None

    # ------------------------------------------------------------------ GC
    def gc(self, db: Session) -> dict:
        """Weekly cleanup (config/memory.yaml). Unused-time limits are per layer: L1 goes stale at 30 days and is
        archived at `stale_after_days_unused` (60); L3 lives `ttl_days_since_last_use` (180). A standing rule
        follows its own expiry. L3 over `max_entries` per scope is compacted (lowest score archived first)."""
        layers = self.cfg.memory["layers"]
        l1_archive = int(layers["L1_dept_playbook"].get("stale_after_days_unused", 60))
        l3_ttl = int(layers["L3_employee_private"].get("ttl_days_since_last_use", 180))
        l3_max = int(layers["L3_employee_private"].get("max_entries", 300))
        report = {"deduped": 0, "stale": 0, "archived": 0, "expired": 0, "compacted": 0}
        active = list(db.scalars(select(MemoryEntry).where(MemoryEntry.status.in_(["active", "stale"]))))
        seen: dict[tuple, MemoryEntry] = {}
        kept: list[MemoryEntry] = []
        for m in active:
            if m.pinned:
                continue
            key = (m.layer, m.scope_id, m.content.strip().lower())
            if key in seen:
                m.status = "archived"
                report["deduped"] += 1
                continue
            seen[key] = m
            last = _aware(m.last_used_at) or _aware(m.created_at)
            age = (now() - last).days
            limit = l3_ttl if m.layer == "L3" else l1_archive
            if _aware(m.expires_at):
                expired = _aware(m.expires_at) < now()
                limit = None   # a standing rule lives until its own expiry date, not the unused-days limit
            else:
                expired = False
            if expired:
                m.status = "archived"
                report["expired"] += 1
            elif limit is not None and age >= limit:
                m.status = "archived"
                report["archived"] += 1
            elif limit is not None and m.layer != "L3" and age >= 30 and m.status == "active":
                m.status = "stale"
                report["stale"] += 1
            else:
                kept.append(m)
        by_scope: dict[str, list[MemoryEntry]] = {}
        for m in kept:
            if m.layer == "L3":
                by_scope.setdefault(m.scope_id, []).append(m)
        for rows in by_scope.values():
            if len(rows) > l3_max:
                rows.sort(key=lambda m: (m.confidence or 0.5) * 0.97 ** (now() - (_aware(m.last_used_at) or _aware(m.created_at))).days)
                for m in rows[:len(rows) - l3_max]:
                    m.status = "archived"
                    report["compacted"] += 1
        db.add(AuditEvent(actor="librarian", kind="memory_gc", detail=report))
        return report
