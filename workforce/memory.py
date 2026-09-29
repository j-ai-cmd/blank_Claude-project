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
    def readable_scopes(self, emp: Employee) -> list[tuple[str, str]]:
        scopes: list[tuple[str, str]] = []
        for grant in emp.memory_read:
            if grant == "L3_self":
                scopes.append(("L3", emp.id))
            elif grant.startswith("L1") and emp.dept:
                scopes += [("L1", emp.dept), ("L1_daily", emp.dept)]
            elif grant == "L1_all_depts_readonly" or grant == "L1_all":
                scopes += [("L1", d) for d in self.cfg.org["departments"]]
            elif grant == "L1_task_dept":
                pass  # resolved per task by caller
        return scopes

    def read(self, db: Session, emp: Employee, query: str = "", limit: int = 12,
             extra_scopes: list[tuple[str, str]] | None = None) -> list[MemoryEntry]:
        scopes = self.readable_scopes(emp) + (extra_scopes or [])
        if not scopes:
            return []
        cond = or_(*[(MemoryEntry.layer == l) & (MemoryEntry.scope_id == s) for l, s in scopes])
        rows = list(db.scalars(select(MemoryEntry).where(cond, MemoryEntry.status == "active")))
        words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 2}

        def score(m: MemoryEntry) -> float:
            rel = 1.0 + (len(words & set(re.findall(r"\w+", m.content.lower()))) if words else 0)
            age = (now() - (_aware(m.last_used_at) or _aware(m.created_at))).days
            return rel * (0.97 ** age) * (m.confidence or 0.5) + (5 if m.pinned else 0)

        rows.sort(key=score, reverse=True)
        picked = rows[:limit]
        for m in picked:
            m.last_used_at = now()
        return picked

    # ------------------------------------------------------------------ candidates
    def submit_candidate(self, db: Session, emp: Employee, task: Task, content: str, kind: str = "feedback",
                         layer: str = "L3", source: str | None = None, pointer: str | None = None,
                         derived_from_untrusted: bool = False, standing: bool = False) -> MemoryEntry:
        scope = emp.id if layer == "L3" else (emp.dept or task.department)
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

    # ------------------------------------------------------------------ GC
    def gc(self, db: Session) -> dict:
        report = {"deduped": 0, "stale": 0, "archived": 0, "expired": 0}
        active = list(db.scalars(select(MemoryEntry).where(MemoryEntry.status.in_(["active", "stale"]))))
        seen: dict[tuple, MemoryEntry] = {}
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
            if _aware(m.expires_at) and _aware(m.expires_at) < now():
                m.status = "archived"
                report["expired"] += 1
            elif age >= 60:
                m.status = "archived"
                report["archived"] += 1
            elif age >= 30 and m.status == "active":
                m.status = "stale"
                report["stale"] += 1
        db.add(AuditEvent(actor="librarian", kind="memory_gc", detail=report))
        return report
