from sqlalchemy import Column, Float, Integer, String, DateTime, Text, JSON, func, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm.attributes import NO_VALUE

from app.db.base import Base


class XHSAccountNote(Base):
    __tablename__ = "xhs_account_notes"
    __table_args__ = (
        UniqueConstraint("environment_id", "feed_id", name="uq_xhs_account_notes_env_feed"),
    )

    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=False, index=True, comment="云登环境ID")

    account_name = Column(String(200), nullable=False, default="", comment="抓取时的账号名称")
    profile_nickname = Column(String(200), nullable=True, comment="小红书主页昵称")
    red_id = Column(String(100), nullable=True, comment="小红书号")

    feed_id = Column(String(100), nullable=False, index=True, comment="帖子ID")
    xsec_token = Column(String(255), nullable=True, comment="帖子安全令牌")
    post_url = Column(String(600), nullable=True, comment="完整帖子链接")
    cover_image_url = Column(String(1000), nullable=True, comment="帖子封面图")
    title = Column(String(255), nullable=False, default="", comment="帖子标题")
    content = Column(Text, nullable=True, comment="帖子正文")
    image_urls = Column(JSON, nullable=True, comment="帖子图片列表")
    ai_origin_type = Column(String(20), nullable=False, default="", comment="manual/text_ai/image_ai/all_ai")
    primary_content_tag = Column(String(80), nullable=True, comment="AI 内容一级标签")
    secondary_content_tag = Column(String(120), nullable=True, comment="AI 内容二级标签")
    status = Column(String(20), nullable=False, default="active", comment="账号帖子状态 active/offline")
    content_status = Column(String(40), nullable=True, comment="正文同步状态")
    content_missing_reason = Column(String(255), nullable=True, comment="正文缺失原因")

    liked_count = Column(Integer, nullable=False, default=0, comment="点赞数")
    comment_count = Column(Integer, nullable=False, default=0, comment="评论数")
    collected_count = Column(Integer, nullable=False, default=0, comment="收藏数")
    share_count = Column(Integer, nullable=False, default=0, comment="转发数")
    view_count = Column(Integer, nullable=False, default=0, comment="浏览量")
    exposure_count = Column(Integer, nullable=False, default=0, comment="曝光量")
    cover_click_rate = Column(Float, nullable=False, default=0.0, comment="封面点击率百分比")
    is_promoted = Column(Boolean, nullable=False, default=False, server_default="false", index=True, comment="是否在投流报表中出现")
    promoted_first_seen_at = Column(DateTime, nullable=True, comment="首次在投流报表中出现")
    promoted_last_seen_at = Column(DateTime, nullable=True, comment="最近在投流报表中出现")
    promoted_source = Column(String(64), nullable=True, comment="投流来源报表")
    published_at = Column(DateTime, nullable=True, comment="帖子发布时间")
    detail_synced_at = Column(DateTime, nullable=True, comment="最近一次详情同步时间")
    sort_index = Column(Integer, nullable=False, default=0, comment="主页列表顺序，0为最新")
    assigned_runner_environment_id = Column(
        Integer,
        ForeignKey("xhs_environments.id"),
        nullable=True,
        index=True,
        comment="当前分配给哪个测试同步环境处理/浏览",
    )
    assignment_updated_at = Column(DateTime, nullable=True, comment="最近一次分配同步环境的时间")

    first_synced_at = Column(DateTime, nullable=True, comment="首次同步时间")
    last_seen_at = Column(DateTime, nullable=True, comment="最近一次在主页列表中看到的时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    environment = relationship("XHSEnvironment", foreign_keys=[environment_id])
    assigned_runner_environment = relationship("XHSEnvironment", foreign_keys=[assigned_runner_environment_id])

    @property
    def assigned_runner_account_name(self):
        loaded_value = sa_inspect(self).attrs.assigned_runner_environment.loaded_value
        runner = None if loaded_value is NO_VALUE else loaded_value
        return getattr(runner, "account_name", None)
