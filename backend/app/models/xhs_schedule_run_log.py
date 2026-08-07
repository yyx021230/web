from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.db.base import Base


class XHSScheduleRunLog(Base):
    __tablename__ = "xhs_schedule_run_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_key = Column(String(64), nullable=False, index=True, comment="任务唯一键")
    source = Column(String(32), nullable=False, default="schedule", server_default="schedule", comment="触发来源")
    status = Column(String(32), nullable=False, default="running", server_default="running", comment="执行状态")
    message = Column(Text, nullable=True, comment="执行结果")
    started_at = Column(DateTime, server_default=func.now(), nullable=False, comment="开始时间(UTC naive)")
    finished_at = Column(DateTime, nullable=True, comment="结束时间(UTC naive)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
