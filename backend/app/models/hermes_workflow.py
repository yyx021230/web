from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class HermesWorkflowSchedule(Base):
    """Administrator-owned daily Hermes production configuration."""

    __tablename__ = "hermes_workflow_schedules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True, default="Hermes 每日 8×5")
    enabled = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    run_time = Column(String(5), nullable=False, default="09:00", server_default="09:00")
    timezone = Column(String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai")
    posts_per_account = Column(Integer, nullable=False, default=5, server_default="5")
    accounts = Column(JSON, nullable=False, default=list)
    instruction = Column(Text, nullable=True)
    last_enqueued_for = Column(Date, nullable=True, index=True)
    last_run_id = Column(Integer, nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class HermesWorkflowRun(Base):
    """One user or scheduled Hermes content-production request."""

    __tablename__ = "hermes_workflow_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_key = Column(String(64), nullable=False, unique=True, index=True)
    source = Column(String(24), nullable=False, default="manual", index=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    schedule_id = Column(Integer, ForeignKey("hermes_workflow_schedules.id"), nullable=True, index=True)
    scheduled_for = Column(Date, nullable=True, index=True)
    parameters = Column(JSON, nullable=False, default=dict)
    total_posts = Column(Integer, nullable=False, default=0, server_default="0")
    generated_posts = Column(Integer, nullable=False, default=0, server_default="0")
    approved_posts = Column(Integer, nullable=False, default=0, server_default="0")
    rejected_posts = Column(Integer, nullable=False, default=0, server_default="0")
    worker_id = Column(String(160), nullable=True, index=True)
    output_manifest = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    publish_requested_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    posts = relationship(
        "HermesWorkflowPost",
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class HermesWorkflowPost(Base):
    """Reviewable account-level content generated inside a Hermes run."""

    __tablename__ = "hermes_workflow_posts"
    __table_args__ = (
        UniqueConstraint("run_id", "environment_id", "slot", name="uq_hermes_run_environment_slot"),
    )

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("hermes_workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=False, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    slot = Column(Integer, nullable=False)
    account_name = Column(String(200), nullable=False)
    vehicle_model = Column(String(160), nullable=False)
    case_id = Column(String(120), nullable=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    title = Column(String(80), nullable=True)
    content = Column(Text, nullable=True)
    image_url = Column(String(1200), nullable=True)
    hard_pass = Column(Boolean, nullable=False, default=False, server_default="false")
    source_detail = Column(JSON, nullable=True)
    review_comment = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    publish_status = Column(String(32), nullable=False, default="not_requested", server_default="not_requested", index=True)
    publish_external_id = Column(String(200), nullable=True)
    publish_target_environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=True, index=True)
    scheduled_publish_at = Column(DateTime, nullable=True, index=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    run = relationship("HermesWorkflowRun", back_populates="posts")


class HermesWorkerState(Base):
    """Heartbeat record for an external machine running the local Hermes engine."""

    __tablename__ = "hermes_worker_states"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(String(160), nullable=False, unique=True, index=True)
    status = Column(String(32), nullable=False, default="idle", server_default="idle", index=True)
    current_run_id = Column(Integer, ForeignKey("hermes_workflow_runs.id"), nullable=True, index=True)
    capabilities = Column(JSON, nullable=False, default=dict)
    last_seen_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
