from sqlalchemy import Column, Integer, String, DateTime, func, Boolean
from sqlalchemy.orm import relationship
from app.db.base import Base
from app.models.user_workflow import user_workflow_access


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    avatar = Column(String(500))
    is_active = Column(Boolean, default=True)
    role = Column(String(20), nullable=False, default="viewer")  # admin, viewer
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    workflows = relationship(
        "DifyWorkflowConfig",
        secondary=user_workflow_access,
        back_populates="users"
    )
