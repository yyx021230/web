"""Immutable external observations and their local application receipts."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func

from app.db.base import Base


class XHSCloudImport(Base):
    __tablename__ = "xhs_cloud_imports"
    __table_args__ = (UniqueConstraint("client_id", "run_id", "item_id", name="uq_xhs_cloud_import_identity"),)

    id = Column(Integer, primary_key=True)
    client_id = Column(String(120), nullable=False)
    run_id = Column(String(64), nullable=False)
    item_id = Column(String(32), nullable=False)
    environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=True, index=True)
    account_id = Column(Integer, ForeignKey("xhs_accounts.id"), nullable=True, index=True)
    payload_hash = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="received")
    error_code = Column(String(100), nullable=True)
    captured_at = Column(DateTime, nullable=True, index=True)
    applied_at = Column(DateTime, nullable=True)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
