from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
        CheckConstraint(
            "progress_current >= 0", name="ck_jobs_progress_current_nonnegative"
        ),
        CheckConstraint(
            "progress_total >= 0", name="ck_jobs_progress_total_nonnegative"
        ),
        CheckConstraint("retry_count >= 0", name="ck_jobs_retry_count_nonnegative"),
        CheckConstraint("max_retries >= 0", name="ck_jobs_max_retries_nonnegative"),
        CheckConstraint("priority >= 0", name="ck_jobs_priority_nonnegative"),
        Index(
            "ix_jobs_claimable",
            "status",
            "worker_type",
            "run_after",
            "priority",
            "created_at",
        ),
        Index("ix_jobs_source", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    scope_key: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="internal",
        server_default="internal",
        index=True,
    )
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    worker_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="server", server_default="server"
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=JobStatus.QUEUED.value,
        server_default=JobStatus.QUEUED.value,
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_summary: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, nullable=True
    )
    progress_current: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    progress_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    current_step: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)

    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    run_after: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    lease_owner: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    user_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    internal_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list[JobItem]] = relationship(
        "JobItem",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    attempts: Mapped[list[JobAttempt]] = relationship(
        "JobAttempt",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    events: Mapped[list[JobEvent]] = relationship(
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
        CheckConstraint(
            "attempt_count >= 0", name="ck_job_items_attempt_count_nonnegative"
        ),
        Index("ix_job_items_job_status", "job_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_key: Mapped[str] = mapped_column(String(160), nullable=False)
    item_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=JobStatus.QUEUED.value,
        server_default=JobStatus.QUEUED.value,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    user_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    internal_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    job: Mapped[Job] = relationship("Job", back_populates="items")


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_job_attempts_job_number"),
        CheckConstraint("attempt_number >= 1", name="ck_job_attempts_number_positive"),
        Index("ix_job_attempts_job_status", "job_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=JobStatus.RUNNING.value,
        server_default=JobStatus.RUNNING.value,
    )
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    user_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    internal_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    job: Mapped[Job] = relationship("Job", back_populates="attempts")


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_job_created", "job_id", "created_at", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="info", server_default="info"
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    actor_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="system", server_default="system"
    )
    actor_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    job: Mapped[Job] = relationship("Job", back_populates="events")
