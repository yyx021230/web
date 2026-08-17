from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class XHSCreatorSyncRow(Base):
    """Normalized creator-center export row kept for reconciliation and audit."""

    __tablename__ = "xhs_creator_sync_rows"
    __table_args__ = (
        UniqueConstraint("sync_run_id", "environment_id", "source_row_index", name="uq_xhs_creator_sync_run_row"),
    )

    id = Column(Integer, primary_key=True, index=True)
    sync_run_id = Column(Integer, ForeignKey("xhs_account_sync_runs.id"), nullable=True, index=True)
    environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=False, index=True)
    matched_note_id = Column(Integer, ForeignKey("xhs_account_notes.id"), nullable=True, index=True)
    source_row_index = Column(Integer, nullable=False)
    source_key = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False, default="")
    published_at = Column(DateTime, nullable=True, index=True)
    published_at_raw = Column(String(100), nullable=True)
    metrics = Column(JSON, nullable=False, default=dict)
    raw_payload = Column(JSON, nullable=False, default=dict)
    match_status = Column(String(32), nullable=False, default="pending", server_default="pending", index=True)
    match_method = Column(String(40), nullable=True)
    match_confidence = Column(Float, nullable=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    sync_run = relationship("XHSAccountSyncRun", foreign_keys=[sync_run_id])
    environment = relationship("XHSEnvironment", foreign_keys=[environment_id])
    matched_note = relationship("XHSAccountNote", foreign_keys=[matched_note_id])
