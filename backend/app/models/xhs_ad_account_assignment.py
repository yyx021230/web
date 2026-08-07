from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, func
from app.db.base import Base


class XHSAdAccountBuyerAssignment(Base):
    __tablename__ = "xhs_ad_account_buyer_assignments"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_xhs_ad_account_buyer_account"),
    )

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(String(64), nullable=False, index=True)
    account_name = Column(String(255), nullable=False, server_default="")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class XHSAdAccountProfessionalMapping(Base):
    __tablename__ = "xhs_ad_account_professional_mappings"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_xhs_ad_account_professional_account"),
    )

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(String(64), nullable=False, index=True)
    account_name = Column(String(255), nullable=False, server_default="")
    xhs_account_id = Column(String(64), nullable=False, index=True)
    xhs_account_name = Column(String(255), nullable=False, server_default="")
    xhs_owner_name = Column(String(100), nullable=False, server_default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
