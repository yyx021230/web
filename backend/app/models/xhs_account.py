"""Account identities are independent of browser execution environments."""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    event,
    func,
    inspect,
)

from app.db.base import Base


class XHSAccount(Base):
    __tablename__ = "xhs_accounts"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True)
    xhs_account_id = Column(String(100), nullable=False, unique=True, index=True)
    account_name = Column(String(200), nullable=False)
    profile_url = Column(String(1000), nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    department = Column(String(32), nullable=False, index=True)
    account_type = Column(String(40), nullable=False)
    status = Column(String(24), nullable=False, index=True)
    owner_label = Column(String(255), nullable=False, default="")
    login_phone_number = Column(String(30), nullable=True)
    sim_device_label = Column(String(100), nullable=False, default="")
    login_device_label = Column(String(100), nullable=False, default="")
    source_row = Column(Integer, nullable=False)
    source_hash = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


@event.listens_for(XHSAccount, "before_update")
def immutable_account_identity(_mapper, _connection, target):
    if inspect(target).attrs.xhs_account_id.history.has_changes():
        raise ValueError(
            "Changing an account ID requires a separate account; retain its historical identity"
        )


class XHSAccountMasterImport(Base):
    __tablename__ = "xhs_account_master_imports"

    id = Column(String(32), primary_key=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    source_hash = Column(String(64), nullable=False)
    baseline_hash = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(24), nullable=False, default="preview")
    result = Column(JSON, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class XHSAccountHistoryLink(Base):
    """Review evidence, never an instruction to rewrite all notes in an environment."""

    __tablename__ = "xhs_account_history_links"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "environment_id", name="uq_xhs_account_history_link"
        ),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(
        Integer, ForeignKey("xhs_accounts.id"), nullable=False, index=True
    )
    environment_id = Column(Integer, ForeignKey("xhs_environments.id"), nullable=False)
    xhs_id_snapshot = Column(String(100), nullable=False)
    status = Column(String(24), nullable=False, default="pending")
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
