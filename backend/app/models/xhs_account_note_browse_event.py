from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class XHSAccountNoteBrowseEvent(Base):
    __tablename__ = "xhs_account_note_browse_events"

    id = Column(Integer, primary_key=True, index=True)
    note_id = Column(Integer, ForeignKey("xhs_account_notes.id"), nullable=False, index=True, comment="账号帖子ID")
    runner_environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=False, index=True, comment="记录到哪个测试账号")
    browse_source = Column(String(40), nullable=False, index=True, comment="link_click/single_sync/bulk_sync")
    job_id = Column(String(64), nullable=True, index=True, comment="关联同步任务ID")
    note_feed_id = Column(String(100), nullable=True, index=True, comment="事件发生时的帖子feed_id")
    note_title = Column(String(255), nullable=True, comment="事件发生时的帖子标题")
    note_post_url = Column(String(600), nullable=True, comment="事件发生时的帖子链接")
    source_environment_id = Column(Integer, nullable=True, index=True, comment="帖子所属账号环境ID")
    source_account_name = Column(String(200), nullable=True, comment="帖子所属账号名称")
    owner_runner_environment_id = Column(Integer, nullable=True, index=True, comment="获取链接账号环境ID快照")
    owner_runner_account_name = Column(String(200), nullable=True, comment="获取链接账号名称快照")
    runner_account_name = Column(String(200), nullable=True, comment="测试账号名称快照")
    created_at = Column(DateTime, server_default=func.now(), index=True)

    note = relationship("XHSAccountNote")
    runner_environment = relationship("XHSEnvironment", foreign_keys=[runner_environment_id])
