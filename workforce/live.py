"""Live Office feed: who is working, who holds each task's note, and every handoff, in real time.

The Dispatcher reports what happens (runs, handoffs, transitions, approvals, posts); this module turns
that into a numbered event stream plus a presence map, for the animated office frontend (SSE).
Events live in memory (ring buffer); after a restart the frontend reloads the snapshot.
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import AsyncIterator, Callable

# Presence states, strongest first: an employee shows the first one that applies.
PAUSED, WORKING, BLOCKED, WAITING_OWNER, SUPERVISING, SLEEPING = (
    "paused", "working", "blocked", "waiting_owner", "supervising", "sleeping")
SUPERVISED_STATUSES = {"CONTRACT_APPROVED", "PLANNED", "IN_PROGRESS", "VERIFYING", "REVISION"}
OWNER = "owner"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


FINISHED_CAP = 5000   # closed tasks remembered so a late walk can't revive their note


class LiveBus:
    def __init__(self, employee_ids: list[str], owner_of: Callable[[str], str | None] | None = None,
                 buffer: int = 2000):
        self.events: deque[dict] = deque(maxlen=buffer)
        self.seq = 0
        self.subscribers: set[asyncio.Queue] = set()
        self.overflowed: set[asyncio.Queue] = set()
        self.owner_of = owner_of or (lambda dept: None)  # dept -> employee who owns tasks of that dept
        self.presence: dict[str, dict] = {e: {"state": SLEEPING, "task_id": None, "phase": None, "since": _now()}
                                          for e in employee_ids}
        self._runs: dict[str, list[tuple[str, str]]] = {e: [] for e in employee_ids}   # active (task, phase)
        self._supervising: dict[str, set[str]] = {e: set() for e in employee_ids}     # task ids
        self._blocked: dict[str, set[str]] = {e: set() for e in employee_ids}
        self._awaiting: dict[str, str] = {}      # approval id -> employee waiting on the owner
        self._approval_task: dict[str, str] = {}
        self._paused: set[str] = set()           # employee ids currently paused
        self.holder: dict[str, str] = {}
        self._finished: dict[str, None] = {}     # closed task ids (insertion-ordered, capped at FINISHED_CAP)

    # ------------------------------------------------------------------ publish / subscribe
    def publish(self, type_: str, task_id: str | None = None, **data) -> dict:
        self.seq += 1
        ev = {"seq": self.seq, "at": _now(), "type": type_, "task_id": task_id, "data": data}
        self.events.append(ev)
        for q in list(self.subscribers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:  # slow client: tell it to reload the snapshot
                self.subscribers.discard(q)
                self.overflowed.add(q)
        return ev

    def since(self, seq: int) -> list[dict] | None:
        """Events after `seq`, or None when they have fallen out of the buffer (client must resync)."""
        if seq >= self.seq:
            return []
        if self.events and seq < self.events[0]["seq"] - 1:
            return None
        return [e for e in self.events if e["seq"] > seq]

    def subscribe(self, maxsize: int = 1000) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)
        self.overflowed.discard(q)

    # ------------------------------------------------------------------ presence
    def _settle(self, emp: str) -> None:
        if emp not in self.presence:
            return
        runs = self._runs[emp]
        if emp in self._paused:
            state, task, phase = PAUSED, None, None
        elif runs:
            (task, phase), state = runs[-1], WORKING
        elif self._blocked[emp]:
            state, task, phase = BLOCKED, sorted(self._blocked[emp])[0], None
        elif emp in self._awaiting.values():
            aid = next(a for a, e in self._awaiting.items() if e == emp)
            state, task, phase = WAITING_OWNER, self._approval_task.get(aid), None
        elif self._supervising[emp]:
            state, task, phase = SUPERVISING, sorted(self._supervising[emp])[0], None
        else:
            state, task, phase = SLEEPING, None, None
        cur = self.presence[emp]
        if (cur["state"], cur["task_id"], cur["phase"]) != (state, task, phase):
            prev = cur["state"]
            self.presence[emp] = {"state": state, "task_id": task, "phase": phase, "since": _now()}
            self.publish("employee.state", task, employee_id=emp, state=state, previous=prev, phase=phase)

    def run_started(self, emp: str, task_id: str, phase: str) -> None:
        if emp in self._runs:
            self._runs[emp].append((task_id, phase))
            self._settle(emp)

    def run_finished(self, emp: str, task_id: str, phase: str, cost_usd: float, error: bool) -> None:
        if emp in self._runs and (task_id, phase) in self._runs[emp]:
            self._runs[emp].remove((task_id, phase))
        self.publish("run.finished", task_id, employee_id=emp, phase=phase, cost_usd=round(cost_usd, 4), error=error)
        self._settle(emp)

    def set_paused(self, emp_ids: set[str]) -> None:
        changed = self._paused ^ emp_ids
        self._paused = set(emp_ids)
        for e in changed:
            self._settle(e)

    # ------------------------------------------------------------------ task flow
    def handoff(self, task_id: str, frm: str, to: str, kind: str, note: str = "", **extra) -> None:
        """Someone walks a note to someone else. `frm`/`to` are employee ids or "owner"."""
        if task_id not in self._finished:   # a late walk (e.g. "part done") must not revive a closed note
            self.holder[task_id] = to
        self.publish("handoff", task_id, **{"from": frm, "to": to, "kind": kind, "note": note[:280], **extra})

    def task_created(self, task_id: str, dept: str, to: str, text: str, parent_id: str | None) -> None:
        self.publish("task.created", task_id, department=dept, assignee=to, request=text[:500], parent_id=parent_id)

    def on_transition(self, task_id: str, dept: str, frm: str, to: str, actor: str, reason: str) -> None:
        self.publish("task.status", task_id, **{"from": frm, "to": to, "actor": actor, "reason": reason[:280]})
        owner = self.owner_of(dept)
        if not owner or owner not in self.presence:
            return
        (self._supervising[owner].add if to in SUPERVISED_STATUSES else self._supervising[owner].discard)(task_id)
        (self._blocked[owner].add if to == "ESCALATED" else self._blocked[owner].discard)(task_id)
        if to == "ESCALATED":
            self.handoff(task_id, self.holder.get(task_id, owner), OWNER, "escalation", reason)
        if to in ("CANCELLED", "CLOSED"):
            self.holder.pop(task_id, None)
            self._finished[task_id] = None
            while len(self._finished) > FINISHED_CAP:   # bounded: months of tasks never grow memory
                del self._finished[next(iter(self._finished))]
        self._settle(owner)

    def approval_requested(self, approval_id: str, task_id: str, gate: str, employee: str | None, title: str,
                           summary: str, action_hash: str | None = None, **extra) -> None:
        if employee:
            self._awaiting[approval_id] = employee
        self._approval_task[approval_id] = task_id
        self.publish("approval.requested", task_id, approval_id=approval_id, gate=gate, employee_id=employee,
                     title=title, summary=summary[:1500], action_hash=action_hash, **extra)
        if employee:
            self._settle(employee)

    def approval_closed(self, approval_id: str, status: str) -> None:
        emp = self._awaiting.pop(approval_id, None)
        task_id = self._approval_task.pop(approval_id, None)
        self.publish("approval.decided", task_id, approval_id=approval_id, status=status)
        if emp:
            self._settle(emp)

    def said(self, task_id: str | None, employee: str | None, text: str) -> None:
        self.publish("message", task_id, employee_id=employee, text=text[:600])

    def seed_task(self, task_id: str, owner: str, status: str) -> None:
        if owner not in self.presence:
            return
        if status in SUPERVISED_STATUSES:
            self._supervising[owner].add(task_id)
        elif status == "ESCALATED":
            self._blocked[owner].add(task_id)
        self.holder.setdefault(task_id, OWNER if status in ("CONTRACT_DRAFTED", "DELIVERED", "ESCALATED") else owner)
        self._settle_quiet(owner)

    def seed_approval(self, approval_id: str, task_id: str, employee: str | None) -> None:
        self._approval_task[approval_id] = task_id
        if employee in self.presence:
            self._awaiting[approval_id] = employee
            self._settle_quiet(employee)

    def _settle_quiet(self, emp: str) -> None:
        seq, n = self.seq, len(self.events)
        self._settle(emp)
        while len(self.events) > n:  # seeding restores state; it is not news
            self.events.pop()
        self.seq = seq

    # ------------------------------------------------------------------ snapshot
    def snapshot(self) -> dict:
        return {"seq": self.seq, "presence": self.presence, "holders": self.holder,
                "pending_approvals": [{"approval_id": a, "task_id": self._approval_task.get(a), "employee_id": e}
                                      for a, e in self._awaiting.items()]}


async def sse(bus: LiveBus, since: int | None, heartbeat_s: float = 15.0) -> AsyncIterator[str]:
    """Server-Sent Events: replays events after `since`, then streams live. `id:` = seq."""
    q = bus.subscribe()
    try:
        backlog = bus.since(since) if since is not None else []
        if backlog is None:
            yield _frame({"seq": bus.seq, "type": "resync", "data": {}}, with_id=False)
            backlog = []
        last = since or 0
        for ev in backlog:
            last = ev["seq"]
            yield _frame(ev)
        yield _frame({"seq": bus.seq, "type": "hello", "data": {"seq": bus.seq}}, with_id=False)
        while True:
            if q in bus.overflowed:
                yield _frame({"seq": bus.seq, "type": "resync", "data": {}}, with_id=False)
                return
            try:
                ev = await asyncio.wait_for(q.get(), timeout=heartbeat_s)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if ev["seq"] <= last:
                continue
            last = ev["seq"]
            yield _frame(ev)
    finally:
        bus.unsubscribe(q)


def _frame(ev: dict, with_id: bool = True) -> str:
    head = f"id: {ev['seq']}\n" if with_id else ""
    return f"{head}event: {ev['type']}\ndata: {json.dumps(ev)}\n\n"
