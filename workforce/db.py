"""Persistence. Postgres in production (DATABASE_URL), SQLite for local/dev/tests."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Task(Base):
    """A Task Contract + its lifecycle (schemas/task_contract.json)."""
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    show: Mapped[str | None] = mapped_column(String(32), nullable=True)   # the ONE show this task belongs to
    department: Mapped[str] = mapped_column(String(40))
    requested_by: Mapped[str] = mapped_column(String(64))
    original_request: Mapped[str] = mapped_column(Text)
    contract: Mapped[dict] = mapped_column(JSON, default=dict)   # current contract body
    contract_version: Mapped[int] = mapped_column(Integer, default=0)
    size: Mapped[str | None] = mapped_column(String(2), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="RECEIVED")
    slack_channel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slack_thread: Mapped[str | None] = mapped_column(String(64), nullable=True)
    g1_approval_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    verification_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    plan: Mapped[list] = mapped_column(JSON, default=list)       # handoff packets
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    revisions: Mapped[int] = mapped_column(Integer, default=0)
    contains_pii: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Approval(Base):
    """G1/G2/G3/G4 gates. G3 approvals are bound to one action hash."""
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    gate: Mapped[str] = mapped_column(String(4))            # G1 G2 G3 G4
    tier: Mapped[str | None] = mapped_column(String(4), nullable=True)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_version: Mapped[int] = mapped_column(Integer, default=0)
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending approved rejected expired used
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PipelineItem(Base):
    """Every pitch / application / invoice that went out (created by code when an approved send runs)."""
    __tablename__ = "pipeline"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))                 # pitch | application | invoice | follow_up
    to: Mapped[str] = mapped_column(String(320), default="")      # recipient / company
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")          # what was sent (Apply and Voice learn from past sends)
    status: Mapped[str] = mapped_column(String(24), default="sent")
    note: Mapped[str] = mapped_column(Text, default="")
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    delivered_via: Mapped[str] = mapped_column(String(20), default="outbox")   # smtp | outbox
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    follow_up_due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    """L5: append-only. Never loaded into agent context."""
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(48))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class MemoryEntry(Base):
    """L1 / L1_daily / L3 (schemas/memory_entry.json). Row ACL by layer + scope_id."""
    __tablename__ = "memory"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    layer: Mapped[str] = mapped_column(String(10))
    scope_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(64))
    verified_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    standing: Mapped[bool] = mapped_column(Boolean, default=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    pointer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supersedes: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="candidate")
    derived_from_untrusted: Mapped[bool] = mapped_column(Boolean, default=False)
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Counter(Base):
    """Per-employee per-day and per-task counters (bulk limits, spend)."""
    __tablename__ = "counters"
    __table_args__ = (UniqueConstraint("scope", "key", "metric"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(80))   # "emp:<id>:<yyyy-mm-dd>" | "task:<id>" | "month:<yyyy-mm>"
    key: Mapped[str] = mapped_column(String(64))
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float, default=0)


class Pause(Base):
    """Kill switches: scope = 'all' | 'dept:<id>' | 'emp:<id>'."""
    __tablename__ = "pauses"
    scope: Mapped[str] = mapped_column(String(80), primary_key=True)
    reason: Mapped[str] = mapped_column(String(200))
    by: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActionRun(Base):
    """Idempotency for external actions: task_id + action_hash executes at most once."""
    __tablename__ = "action_runs"
    __table_args__ = (UniqueConstraint("task_id", "action_hash"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(40))
    action_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # started done failed
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_engine(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL", "sqlite:///var/workforce.db")
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        os.makedirs(os.path.dirname(url.removeprefix("sqlite:///")) or ".", exist_ok=True)
    eng = create_engine(url, future=True)
    Base.metadata.create_all(eng)
    return eng


def make_sessionmaker(url: str | None = None):
    return sessionmaker(bind=make_engine(url), expire_on_commit=False, future=True)
