from sqlalchemy import Column, Integer, ForeignKey, Table
from app.db.base import Base

user_workflow_access = Table(
    "user_workflow_access",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("workflow_id", Integer, ForeignKey("dify_workflows.id", ondelete="CASCADE"), primary_key=True),
)
