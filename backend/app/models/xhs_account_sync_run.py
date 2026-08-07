from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class XHSAccountSyncRun(Base):
    """A durable batch record for account-level homepage sync work."""

    __tablename__ = "xhs_account_sync_runs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(64), unique=True, nullable=False, index=True)
    sync_kind = Column(String(48), nullable=False, index=True, comment="posts/engagement/details")
    source = Column(String(32), nullable=False, default="manual", server_default="manual")
    status = Column(String(32), nullable=False, default="queued", server_default="queued", index=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    parent_run_id = Column(Integer, ForeignKey("xhs_account_sync_runs.id"), nullable=True, index=True)
    request_config = Column(JSON, nullable=False, default=dict, comment="可重放的同步参数快照")
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    items = relationship(
        "XHSAccountSyncRunItem",
        back_populates="run",
        cascade="all, delete-orphan",
        foreign_keys="XHSAccountSyncRunItem.run_id",
        lazy="selectin",
    )


class XHSAccountSyncRunItem(Base):
    __tablename__ = "xhs_account_sync_run_items"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("xhs_account_sync_runs.id"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=True, index=True)
    account_name = Column(String(200), nullable=False, default="")
    status = Column(String(32), nullable=False, default="queued", server_default="queued", index=True)
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    run = relationship("XHSAccountSyncRun", back_populates="items", foreign_keys=[run_id])
