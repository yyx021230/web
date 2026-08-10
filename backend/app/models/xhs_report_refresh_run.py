from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)

from app.db.base import Base


class XHSReportRefreshRun(Base):
    """Persistent evidence for a legacy Xiaohongshu report refresh batch."""

    __tablename__ = "xhs_report_refresh_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_xhs_report_refresh_runs_status",
        ),
        Index(
            "ix_xhs_report_refresh_runs_status_finished",
            "status",
            "finished_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    job_id = Column(String(128), nullable=False, unique=True, index=True)
    source = Column(
        String(32), nullable=False, default="manual", server_default="manual", index=True
    )
    status = Column(
        String(32), nullable=False, default="queued", server_default="queued", index=True
    )
    requested_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    schedule_run_id = Column(
        Integer,
        ForeignKey("xhs_schedule_run_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    request_config = Column(JSON, nullable=False, default=dict)
    result_summary = Column(JSON, nullable=True)
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
