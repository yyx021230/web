from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, func, Boolean
from app.db.base import Base


class DifyWorkflowConfig(Base):
    __tablename__ = "dify_workflows"

    id = Column(Integer, primary_key=True, index=True)
    api_key = Column(String(500), nullable=False)
    base_url = Column(String(500), default="http://8.163.58.214/v1")
    app_name = Column(String(255), nullable=False)
    app_type = Column(String(20), nullable=False)  # workflow, chat, completion
    inputs_schema = Column(JSON, default={})
    description = Column(Text)
    is_enabled = Column(Boolean, default=True)
    created_by = Column(Integer, index=True)
    created_at = Column(DateTime, server_default=func.now())
