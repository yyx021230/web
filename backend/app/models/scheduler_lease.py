from sqlalchemy import Column, DateTime, String, func

from app.db.base import Base


class SchedulerLease(Base):
    __tablename__ = "scheduler_leases"

    lease_key = Column(String(128), primary_key=True)
    owner_id = Column(String(160), nullable=True, index=True)
    acquired_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
