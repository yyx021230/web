from sqlalchemy import Column, Integer, String, JSON, DateTime, func, Text
from app.db.base import Base


class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # image, icon, shape, design, template
    url = Column(String(500), nullable=True)  # 图片素材的URL；设计类可为空
    width = Column(Integer)
    height = Column(Integer)
    category = Column(String(100), index=True)  # editor-design / ai-template 等
    tags = Column(JSON, default=[])
    design_json = Column(JSON, nullable=True)  # 编辑器设计稿的完整 Fabric JSON
    ai_meta = Column(JSON, nullable=True)  # AI 生图元数据: { prompt, ref_images, model, size, style, params }
    file_size = Column(Integer, default=0)  # 文件大小（字节）
    created_by = Column(Integer, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)  # 软删除
    created_at = Column(DateTime, server_default=func.now())
