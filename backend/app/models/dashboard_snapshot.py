from sqlalchemy import Column, DateTime, Integer, JSON, String, UniqueConstraint, func

from app.db.base import Base


class DashboardSnapshot(Base):
    __tablename__ = "dashboard_snapshots"
    __table_args__ = (
        UniqueConstraint("namespace", "cache_key", name="uq_dashboard_snapshots_namespace_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    namespace = Column(String(80), nullable=False, index=True, comment="看板命名空间")
    cache_key = Column(String(128), nullable=False, index=True, comment="参数哈希")
    params = Column(JSON, nullable=False, comment="生成快照的筛选参数")
    payload = Column(JSON, nullable=False, comment="看板结果快照")
    payload_bytes = Column(Integer, nullable=False, default=0, comment="JSON 大小估算")
    generated_at = Column(DateTime, nullable=False, server_default=func.now(), comment="生成时间")
    expires_at = Column(DateTime, nullable=True, index=True, comment="过期时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
