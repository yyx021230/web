"""Durable, account/version-bound cloud phone publishing records."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func

from app.db.base import Base


class HermesPublishJob(Base):
    __tablename__ = "hermes_publish_jobs"
    __table_args__ = (
        Index("ix_hermes_publish_due", "status", "retry_at", "scheduled_at"),
        UniqueConstraint("post_id", name="uq_hermes_publish_post"),
        UniqueConstraint("request_key", name="uq_hermes_publish_request"),
    )

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("hermes_workflow_posts.id"), nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    request_key = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="scheduled")
    snapshot = Column(JSON, nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    retry_at = Column(DateTime, nullable=True)
    claim_token = Column(String(64), nullable=True)
    lease_until = Column(DateTime, nullable=True)
    device_id = Column(String(200), nullable=True)
    app_slot = Column(String(8), nullable=True)
    remote_job_id = Column(String(200), nullable=True)
    error_code = Column(String(80), nullable=True)
    message = Column(String(500), nullable=True)
    events = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class HermesPublishAttempt(Base):
    __tablename__ = "hermes_publish_attempts"
    __table_args__ = (UniqueConstraint("request_key", name="uq_hermes_publish_attempt_request"),)

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("hermes_publish_jobs.id"), nullable=False, index=True)
    request_key = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    remote_job_id = Column(String(200), nullable=True)
    evidence = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
