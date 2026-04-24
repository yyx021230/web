from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, func, Boolean
from app.db.base import Base


class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1000))
    thumbnail = Column(String(500))
    fabric_json = Column(Text, nullable=False)  # Fabric.js JSON
    category = Column(String(100), index=True)
    tags = Column(JSON, default=[])
    created_by = Column(Integer, index=True)
    is_public = Column(Boolean, default=True)
    deleted_at = Column(DateTime, nullable=True, index=True)  # 软删除
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
