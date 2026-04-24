from sqlalchemy import Column, Integer, String, Text, DateTime, func
from app.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    fabric_json = Column(Text)  # Canvas JSON
    thumbnail = Column(String(500))
    status = Column(String(20), default="draft")  # draft, published
    deleted_at = Column(DateTime, nullable=True, index=True)  # 软删除
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
