from abc import ABC, abstractmethod


class StorageAdapter(ABC):
    @abstractmethod
    async def save(self, file_content: bytes, filename: str, content_type: str = "") -> str:
        """保存文件，返回访问 URL"""
        pass

    @abstractmethod
    async def delete(self, url: str) -> None:
        """删除文件"""
        pass

    @abstractmethod
    async def get_url(self, filename: str, expires: int = 3600) -> str:
        """获取文件访问 URL"""
        pass
