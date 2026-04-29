"""文案库模型"""

from sqlalchemy import Column, Integer, String, JSON, DateTime, Text, func
from app.db.base import Base


class Copywriting(Base):
    __tablename__ = "copywritings"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)  # 标题（首行提取）
    content = Column(Text, nullable=False)  # 正文内容
    tags = Column(JSON, default=[])  # 从 #标签 提取的标签列表
    category = Column(String(100), nullable=True, index=True)  # 品牌/车型分类
    created_by = Column(Integer, nullable=True, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)  # 软删除
    created_at = Column(DateTime, server_default=func.now())
