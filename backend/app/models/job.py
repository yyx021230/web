from __future__ import annotations

from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class JobStatus(str, Enum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    WAITING_REVIEW = "waiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


TERMINAL_JOB_STATUSES = frozenset(
    {
        JobStatus.SUCCEEDED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
        JobStatus.DEAD_LETTER.value,
    }
)


class Job(Base):
    """Durable task record shared by future background workers."""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "job_type",
            "idempotency_key",
            name="uq_jobs_scope_type_idempotency",
        ),
        CheckConstraint("progress_current >= 0", name="ck_jobs_progress_current_nonnegative"),
        CheckConstraint("progress_total >= 0", name="ck_jobs_progress_total_nonnegative"),
        CheckConstraint("retry_count >= 0", name="ck_jobs_retry_count_nonnegative"),
        CheckConstraint("max_retries >= 0", name="ck_jobs_max_retries_nonnegative"),
        Index("ix_jobs_claimable", "status", "worker_type", "run_after", "priority", "created_at"),
        Index("ix_jobs_source", "source_type", "source_id"),
    )

    id = Column(Integer, primary_key=True)
    public_id = Column(String(36), nullable=False, unique=True)
    scope_key = Column(String(80), nullable=False, default="internal", server_default="internal", index=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_job_id = Column(Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)

    job_type = Column(String(64), nullable=False, index=True)
    worker_type = Column(String(32), nullable=False, default="server", server_default="server")
    status = Column(
        String(32),
        nullable=False,
        default=JobStatus.QUEUED.value,
        server_default=JobStatus.QUEUED.value,
    )
    priority = Column(Integer, nullable=False, default=100, server_default="100")
    idempotency_key = Column(String(128), nullable=True)
    source_type = Column(String(64), nullable=True)
    source_id = Column(String(128), nullable=True)

    payload = Column(JSON, nullable=False, default=dict)
    result_summary = Column(JSON, nullable=True)
    progress_current = Column(Integer, nullable=False, default=0, server_default="0")
    progress_total = Column(Integer, nullable=False, default=0, server_default="0")
    current_step = Column(String(160), nullable=True)

    retry_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_retries = Column(Integer, nullable=False, default=3, server_default="3")
    cancel_requested = Column(Boolean, nullable=False, default=False, server_default="false")
    run_after = Column(DateTime, nullable=True)
    lease_owner = Column(String(128), nullable=True, index=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    heartbeat_at = Column(DateTime, nullable=True)

    error_code = Column(String(80), nullable=True)
    user_message = Column(Text, nullable=True)
    internal_error = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    items = relationship(
        "JobItem",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    attempts = relationship(
        "JobAttempt",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    events = relationship(
        "JobEvent",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="JobEvent.id",
        lazy="raise",
    )


class JobItem(Base):
    __tablename__ = "job_items"
    __table_args__ = (
        UniqueConstraint("job_id", "item_key", name="uq_job_items_job_key"),
        Index("ix_job_items_job_status", "job_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    item_key = Column(String(160), nullable=False)
    item_type = Column(String(64), nullable=True)
    display_name = Column(String(240), nullable=True)
    status = Column(String(32), nullable=False, default=JobStatus.QUEUED.value, server_default=JobStatus.QUEUED.value)
    payload = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    error_code = Column(String(80), nullable=True)
    user_message = Column(Text, nullable=True)
    internal_error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    job = relationship("Job", back_populates="items")


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_job_attempts_job_number"),
        Index("ix_job_attempts_job_status", "job_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False)
    worker_id = Column(String(128), nullable=True, index=True)
    status = Column(String(32), nullable=False, default=JobStatus.RUNNING.value, server_default=JobStatus.RUNNING.value)
    lease_expires_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    metrics = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(80), nullable=True)
    user_message = Column(Text, nullable=True)
    internal_error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    job = relationship("Job", back_populates="attempts")


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (
        Index("ix_job_events_job_created", "job_id", "created_at", "id"),
    )

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=True)
    level = Column(String(16), nullable=False, default="info", server_default="info")
    message = Column(Text, nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    actor_type = Column(String(32), nullable=False, default="system", server_default="system")
    actor_id = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    job = relationship("Job", back_populates="events")
