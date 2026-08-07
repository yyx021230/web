from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text, func

from app.db.base import Base


class XHSScheduleSetting(Base):
    __tablename__ = "xhs_schedule_settings"

    id = Column(Integer, primary_key=True, index=True)
    task_key = Column(String(64), unique=True, nullable=False, index=True, comment="任务唯一键")
    enabled = Column(Boolean, nullable=False, default=False, server_default="false", comment="是否启用")
    run_time = Column(String(5), nullable=False, default="00:00", server_default="00:00", comment="每日执行时间 HH:MM")
    config = Column(JSON, nullable=False, default=dict, comment="任务配置 JSON")
    last_run_at = Column(DateTime, nullable=True, comment="上次执行时间(UTC naive)")
    last_status = Column(String(32), nullable=True, comment="上次执行状态")
    last_message = Column(Text, nullable=True, comment="上次执行结果")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
