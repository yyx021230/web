from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.db.base import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    credential_digest = Column(String(64), nullable=False)
    refresh_digest = Column(String(64), nullable=False)
    previous_digest = Column(String(64))
    refresh_nonce = Column(String(64), nullable=False)
    generation = Column(Integer, nullable=False, default=0)
    rotated_at = Column(DateTime)
    last_active_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
