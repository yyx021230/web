from sqlalchemy import Column, Integer, ForeignKey, DateTime, func, UniqueConstraint
from app.db.base import Base


class UserXHSEnvironment(Base):
    __tablename__ = "user_xhs_environments"
    __table_args__ = (
        UniqueConstraint("user_id", "environment_id", name="uq_user_env"),
        UniqueConstraint("environment_id", name="uq_user_xhs_env_environment"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
