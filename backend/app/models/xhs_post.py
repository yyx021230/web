from sqlalchemy import Column, Integer, String, DateTime, func, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base import Base


class XHSPost(Base):
    __tablename__ = "xhs_posts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="发布人ID")
    environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=False, index=True, comment="云登环境ID")

    feed_id = Column(String(100), comment="小红书帖子ID")
    xsec_token = Column(String(200), comment="小红书安全令牌")
    post_url = Column(String(500), comment="小红书帖子链接")

    title = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    image_urls = Column(JSON, comment="图片路径列表")
    tags = Column(JSON, comment="标签列表")
    ai_origin_type = Column(String(20), nullable=False, default="manual", comment="manual/text_ai/image_ai/all_ai")

    status = Column(String(20), nullable=False, default="failed", comment="publishing/scheduled/cancelled/success/failed/deleted")

    like_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    collect_count = Column(Integer, default=0)
    share_count = Column(Integer, default=0, comment="转发量")
    view_count = Column(Integer, default=0, comment="浏览量")

    published_at = Column(DateTime)
    scheduled_at = Column(DateTime, comment="定时发布时间")
    last_synced_at = Column(DateTime, comment="最后数据同步时间")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    environment = relationship("XHSEnvironment")
