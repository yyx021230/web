from __future__ import annotations
"""本地文件存储适配器"""

import os
import uuid
import aiofiles
from pathlib import Path
from app.config import settings
from app.adapters.storage.base import StorageAdapter


class LocalStorageAdapter(StorageAdapter):
    """本地文件存储"""

    def __init__(self):
        self.storage_path = Path(settings.storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    async def save(self, file_content: bytes, filename: str, content_type: str = "") -> str:
        """保存文件到本地目录"""
        # 生成唯一文件名，保留原始扩展名
        ext = Path(filename).suffix or ".jpg"
        unique_name = f"{uuid.uuid4().hex}{ext}"
        file_path = self.storage_path / unique_name

        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_content)

        return f"/uploads/{unique_name}"

    async def delete(self, url: str) -> None:
        """删除本地文件"""
        filename = url.split("/")[-1]
        file_path = self.storage_path / filename
        if file_path.exists():
            file_path.unlink()

    async def get_url(self, filename: str, expires: int = 3600) -> str:
        """获取文件访问 URL"""
        return f"/uploads/{filename}"
