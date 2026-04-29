"""提示词库模型"""

from sqlalchemy import Column, Integer, String, JSON, DateTime, Text, ForeignKey, func, Boolean
from sqlalchemy.orm import relationship
from app.db.base import Base


class PromptCategory(Base):
    """提示词分类"""
    __tablename__ = "prompt_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)  # 分类名称
    start_intro = Column(Text, nullable=True)  # 分类简介
    sort_order = Column(Integer, default=0)  # 排序
    deleted_at = Column(DateTime, nullable=True, index=True)  # 软删除
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关联的提示词示例
    examples = relationship("PromptExample", back_populates="category", cascade="all, delete-orphan")


class PromptExample(Base):
    """提示词示例"""
    __tablename__ = "prompt_examples"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("prompt_categories.id"), nullable=False, index=True)
    param_type = Column(String(100), nullable=False, index=True)  # 参数类型（如"角色设计"）
    image_num = Column(Integer, default=0)  # 图片序号
    image_url = Column(String(500), nullable=True)  # 图片URL
    name = Column(String(255), nullable=True)  # 示例名称
    chinese_example = Column(Text, nullable=False)  # 中文提示词
    english_example = Column(Text, nullable=False)  # 英文提示词
    ul_list = Column(JSON, default=[])  # 策略与技巧列表
    sort_order = Column(Integer, default=0)  # 排序
    is_public = Column(Boolean, nullable=False, default=True)  # 是否公开到社区
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # 上传者
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # 最后编辑者
    deleted_at = Column(DateTime, nullable=True, index=True)  # 软删除
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 所属分类
    category = relationship("PromptCategory", back_populates="examples")
