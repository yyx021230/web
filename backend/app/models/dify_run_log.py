from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, Float, func
from app.db.base import Base


class DifyRunLog(Base):
    __tablename__ = "dify_run_logs"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    inputs = Column(JSON, default={})
    outputs = Column(JSON, default={})
    status = Column(String(20), default="running")  # running, succeeded, failed, stopped
    task_id = Column(String(100))
    error = Column(Text)
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime)
    elapsed_ms = Column(Float)
