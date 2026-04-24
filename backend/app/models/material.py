from sqlalchemy import Column, Integer, String, JSON, DateTime, func
from app.db.base import Base


class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # image, icon, shape
    url = Column(String(500), nullable=False)
    width = Column(Integer)
    height = Column(Integer)
    category = Column(String(100), index=True)
    tags = Column(JSON, default=[])
    created_by = Column(Integer, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)  # 软删除
    created_at = Column(DateTime, server_default=func.now())
