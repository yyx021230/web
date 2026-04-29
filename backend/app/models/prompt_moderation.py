"""提示词社区审核相关模型"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, func
from app.db.base import Base


class PromptReport(Base):
    """提示词举报"""
    __tablename__ = "prompt_reports"

    id = Column(Integer, primary_key=True, index=True)
    prompt_id = Column(Integer, ForeignKey("prompt_examples.id"), nullable=False, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reason = Column(String(100), nullable=False, default="其他")
    details = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending/resolved/rejected
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_note = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class PromptAuditLog(Base):
    """提示词审核日志"""
    __tablename__ = "prompt_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    prompt_id = Column(Integer, ForeignKey("prompt_examples.id"), nullable=False, index=True)
    action = Column(String(50), nullable=False)  # report/hide/show/delete/resolve_report
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
