from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, func, Float, UniqueConstraint
from app.db.base import Base


class AITask(Base):
    __tablename__ = "ai_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "client_request_id", name="uq_ai_tasks_user_client_request"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    client_request_id = Column(String(64), nullable=True, index=True)
    model_name = Column(String(50), nullable=False)  # seedream, midjourney, etc.
    prompt = Column(Text, nullable=False)
    negative_prompt = Column(Text)
    params = Column(JSON, default={})  # width, height, style, etc.
    status = Column(String(20), default="pending")  # pending, processing, completed, failed
    result_urls = Column(JSON, default=[])
    error = Column(Text)
    elapsed_seconds = Column(Float)
    created_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime)
