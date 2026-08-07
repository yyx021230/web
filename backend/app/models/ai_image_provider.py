from sqlalchemy import Boolean, Column, DateTime, Float, Integer, JSON, String, Text, func

from app.db.base import Base


class AIImageProvider(Base):
    __tablename__ = "ai_image_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    model_name = Column(String(50), nullable=False, index=True, default="gptimage2")
    provider_kind = Column(String(50), nullable=False, default="openai_images")
    provider_model = Column(String(100), nullable=False, default="gpt-image-2")
    endpoint_url = Column(String(500), nullable=False)
    api_key = Column(String(500), nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    priority = Column(Integer, default=100, nullable=False)
    weight = Column(Integer, default=1, nullable=False)
    supports_text_input = Column(Boolean, default=True, nullable=False)
    supports_image_input = Column(Boolean, default=False, nullable=False)
    config = Column(JSON, default={})
    last_health_status = Column(String(20), default="unknown", nullable=False)
    last_health_error = Column(Text)
    last_checked_at = Column(DateTime)
    last_used_at = Column(DateTime)
    success_count = Column(Integer, default=0, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    avg_latency_ms = Column(Float)
    created_by = Column(Integer, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
