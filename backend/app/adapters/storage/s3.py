"""S3 / MinIO 文件存储适配器"""

from __future__ import annotations

import asyncio
import io
import uuid
from pathlib import Path
from minio import Minio
from minio.error import S3Error
from app.config import settings
from app.adapters.storage.base import StorageAdapter


class S3StorageAdapter(StorageAdapter):
    """S3 / MinIO 文件存储（同步客户端通过 asyncio.to_thread 异步化）"""

    def __init__(self):
        self.client = Minio(
            settings.s3_endpoint.replace("http://", "").replace("https://", ""),
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=settings.s3_endpoint.startswith("https"),
        )
        self.bucket = settings.s3_bucket
        self._ensure_bucket()

    def _ensure_bucket(self):
        """确保 bucket 存在"""
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    async def save(self, file_content: bytes, filename: str, content_type: str = "", subdir: str = "") -> str:
        """上传文件到 S3

        Args:
            subdir: 子目录前缀（如 'drafts', 'templates'），实现逻辑隔离。
        """
        ext = Path(filename).suffix or ".jpg"
        unique_name = f"{uuid.uuid4().hex}{ext}"
        if subdir:
            unique_name = f"{subdir}/{unique_name}"

        data = io.BytesIO(file_content)
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            unique_name,
            data,
            length=len(file_content),
            content_type=content_type or "application/octet-stream",
        )
        return f"{settings.s3_endpoint}/{self.bucket}/{unique_name}"

    async def delete(self, url: str) -> None:
        """从 S3 删除文件"""
        # Extract object key from URL: http://endpoint/bucket/subdir/filename.ext
        full_path = url.replace(f"{settings.s3_endpoint}/{self.bucket}/", "")
        await asyncio.to_thread(self.client.remove_object, self.bucket, full_path)

    async def get_url(self, filename: str, expires: int = 3600) -> str:
        """获取预签名 URL"""
        return await asyncio.to_thread(
            self.client.presigned_get_object, self.bucket, filename, expires=expires
        )
