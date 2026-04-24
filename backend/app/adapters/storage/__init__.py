from __future__ import annotations
"""存储适配器工厂（懒加载，避免启动时 S3 配置错误导致服务无法启动）"""

from typing import TYPE_CHECKING

from app.adapters.storage.base import StorageAdapter

if TYPE_CHECKING:
    from app.adapters.storage.local import LocalStorageAdapter
    from app.adapters.storage.s3 import S3StorageAdapter


_storage_instance: StorageAdapter | None = None


def get_storage() -> StorageAdapter:
    """获取当前配置的存储适配器（懒加载单例）"""
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    from app.config import settings
    from app.adapters.storage.local import LocalStorageAdapter

    storage_type = settings.storage_type
    if storage_type == "local":
        _storage_instance = LocalStorageAdapter()
    elif storage_type in ("s3", "minio"):
        from app.adapters.storage.s3 import S3StorageAdapter
        _storage_instance = S3StorageAdapter()
    else:
        _storage_instance = LocalStorageAdapter()

    return _storage_instance


# 向后兼容：保留 storage 属性访问（懒加载）
def __getattr__(name: str):
    if name == "storage":
        return get_storage()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
