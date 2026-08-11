"""本地文件存储适配器"""

from __future__ import annotations

import os
import uuid
import aiofiles
from pathlib import Path
from urllib.parse import unquote
from app.config import settings
from app.adapters.storage.base import StorageAdapter


class LocalStorageAdapter(StorageAdapter):
    """本地文件存储"""

    def __init__(self):
        self.storage_path = Path(settings.storage_path).resolve()
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative_path: str) -> Path:
        candidate = (self.storage_path / relative_path).resolve()
        root = str(self.storage_path)
        value = str(candidate)
        if value != root and not value.startswith(root + os.sep):
            raise ValueError("非法存储路径")
        return candidate

    async def save(self, file_content: bytes, filename: str, content_type: str = "", subdir: str = "") -> str:
        """保存文件到本地目录

        Args:
            subdir: 子目录（如 'drafts', 'templates'），实现物理隔离。
        """
        ext = Path(filename).suffix or ".jpg"
        unique_name = f"{uuid.uuid4().hex}{ext}"

        if subdir:
            dir_path = self._safe_path(subdir)
            dir_path.mkdir(parents=True, exist_ok=True)
            file_path = dir_path / unique_name
        else:
            file_path = self.storage_path / unique_name

        async with aiofiles.open(file_path, "wb") as f:
            await f.write(file_content)

        path_prefix = f"/{subdir}" if subdir else ""
        return f"/uploads{path_prefix}/{unique_name}"

    async def delete(self, url: str) -> None:
        """删除本地文件"""
        # url format: /uploads[/subdir]/filename.ext
        clean_url = unquote(str(url or "").split("?", 1)[0].split("#", 1)[0])
        relative = clean_url[len("/uploads/"):] if clean_url.startswith("/uploads/") else clean_url.lstrip("/")
        file_path = self._safe_path(relative)
        if file_path.exists():
            file_path.unlink()

    async def get_url(self, filename: str, expires: int = 3600) -> str:
        """获取文件访问 URL"""
        return f"/uploads/{filename}"
