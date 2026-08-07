from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, func

from app.db.base import Base


class VehicleCatalog(Base):
    __tablename__ = "vehicle_catalog"
    __table_args__ = (
        UniqueConstraint("brand", "model", name="uq_vehicle_catalog_brand_model"),
    )

    id = Column(Integer, primary_key=True, index=True)
    mid = Column(String(64), nullable=True, index=True)
    brand = Column(String(100), nullable=False, index=True)
    model = Column(String(160), nullable=False, index=True)
    model_id = Column(String(120), nullable=True, index=True)
    source = Column(String(64), nullable=False, server_default="seed")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class VehicleModelImage(Base):
    __tablename__ = "vehicle_model_images"
    __table_args__ = (
        UniqueConstraint("brand", "model", "label", "url", name="uq_vehicle_model_images_exact"),
    )

    id = Column(Integer, primary_key=True, index=True)
    brand = Column(String(100), nullable=False, index=True)
    model = Column(String(160), nullable=False, index=True)
    label = Column(String(50), nullable=False, index=True)
    url = Column(String(1024), nullable=False)
    sort_order = Column(Integer, nullable=False, server_default="0")
    source = Column(String(64), nullable=False, server_default="seed")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
