"""Task lifecycle with hard transitions (DESIGN-MAP §5). The Dispatcher refuses anything else."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .db import Approval, AuditEvent, Task


class TransitionError(Exception):
    pass


ALLOWED: dict[str, set[str]] = {
    "RECEIVED": {"CONTRACT_DRAFTED", "CANCELLED"},
    "CONTRACT_DRAFTED": {"CONTRACT_APPROVED", "CONTRACT_DRAFTED", "CANCELLED"},
    "CONTRACT_APPROVED": {"PLANNED", "WAITING_ON_DEPT", "CANCELLED"},
    "WAITING_ON_DEPT": {"PLANNED", "ESCALATED", "CONTRACT_DRAFTED", "CANCELLED"},
    "PLANNED": {"IN_PROGRESS", "ESCALATED", "CONTRACT_DRAFTED", "CANCELLED"},
    "IN_PROGRESS": {"VERIFYING", "AWAITING_APPROVAL", "ESCALATED", "CONTRACT_DRAFTED", "CANCELLED"},
    "AWAITING_APPROVAL": {"IN_PROGRESS", "ESCALATED", "CANCELLED"},
    "VERIFYING": {"DELIVERED", "REVISION", "ESCALATED"},
    "REVISION": {"IN_PROGRESS", "WAITING_ON_DEPT", "ESCALATED", "CONTRACT_DRAFTED", "CANCELLED"},
    "DELIVERED": {"ACCEPTED", "REJECTED"},
    "REJECTED": {"REVISION", "CONTRACT_DRAFTED", "CANCELLED"},
    "ACCEPTED": {"CLOSED"},
    "ESCALATED": {"IN_PROGRESS", "CONTRACT_DRAFTED", "CANCELLED"},
    "CANCELLED": set(),
    "CLOSED": set(),
}

TERMINAL = {"CANCELLED", "CLOSED"}


def _approved(db: Session, approval_id: str | None, task: Task, gate: str) -> bool:
    if not approval_id:
        return False
    a = db.get(Approval, approval_id)
    return bool(a and a.task_id == task.id and a.gate == gate and a.status in ("approved", "used")
                and a.contract_version == task.contract_version)


def transition(db: Session, task: Task, to: str, actor: str, reason: str = "") -> None:
    frm = task.status
    if to not in ALLOWED.get(frm, set()):
        raise TransitionError(f"{frm} -> {to} not allowed")
    # guards
    if to == "IN_PROGRESS" and frm == "PLANNED":
        if not (task.g1_approval_id and (_approved(db, task.g1_approval_id, task, "G1")
                                         or task.g1_approval_id.startswith("auto-S") or
                                         task.g1_approval_id.startswith("inherited-"))):
            raise TransitionError("IN_PROGRESS requires a stored G1 approval (or S auto-start / inherited parent)")
    if to == "DELIVERED" and not task.verification_id:
        raise TransitionError("DELIVERED requires a stored verification record")
    if to == "ACCEPTED" and actor == "agent":
        raise TransitionError("only a human can accept")
    task.status = to
    db.add(AuditEvent(task_id=task.id, actor=actor, kind="transition", detail={"from": frm, "to": to, "reason": reason}))
    if bus := db.info.get("live"):
        bus.on_transition(task.id, task.department, frm, to, actor, reason)


def new_contract_version(db: Session, task: Task, contract: dict, actor: str) -> None:
    """A contract change invalidates approvals, plan and verification of the previous version."""
    task.contract_version += 1
    task.contract = contract
    task.plan = []
    task.verification_id = None
    task.g1_approval_id = None
    for a in db.query(Approval).filter(Approval.task_id == task.id, Approval.status.in_(["pending", "confirming"]),
                                       Approval.gate != "GM"):   # standing-rule cards aren't tied to a contract version
        a.status = "expired"
        if bus := db.info.get("live"):
            bus.approval_closed(a.id, "expired")
    db.add(AuditEvent(task_id=task.id, actor=actor, kind="contract_version", detail={"version": task.contract_version}))
