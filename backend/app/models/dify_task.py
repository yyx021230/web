from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, Float, func
from app.db.base import Base


class DifyTask(Base):
    __tablename__ = "dify_tasks"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    task_id = Column(String(100), nullable=True)
    status = Column(String(20), default="pending")  # pending, running, succeeded, failed
    inputs = Column(JSON, default={})
    outputs = Column(JSON, default={})
    error = Column(Text)
    progress = Column(String(255), default="")
    elapsed_ms = Column(Float)
    viewed = Column(Integer, default=0)  # 0=unviewed, 1=viewed
    created_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime)
