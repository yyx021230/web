from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from app.config import settings

MAX_REMOTE_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_REMOTE_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}


def _is_forbidden_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="远程图片来源不可解析")

    for info in infos:
        ip_text = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            raise HTTPException(status_code=400, detail="远程图片来源无效")
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    return False


def _validate_remote_image_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="远程图片来源不被允许")

    host = parsed.hostname.lower()
    allowed_hosts = {item.lower() for item in settings.remote_image_allowed_hosts}
    if host not in allowed_hosts:
        raise HTTPException(status_code=400, detail="远程图片来源不被允许")
    if _is_forbidden_ip(host):
        raise HTTPException(status_code=400, detail="远程图片来源不被允许")
    return host


def _infer_image_mime(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


async def download_allowed_remote_image(url: str, *, timeout: float = 30.0) -> tuple[bytes, str, str]:
    """Download an allowlisted remote image with SSRF, size, and MIME controls."""
    original_host = _validate_remote_image_url(url)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"下载图片失败: HTTP {resp.status_code}")
            final_host = urlparse(str(resp.url)).hostname
            if not final_host or final_host.lower() != original_host:
                _validate_remote_image_url(str(resp.url))

            content_length = resp.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_REMOTE_IMAGE_BYTES:
                        raise HTTPException(status_code=400, detail="远程图片大小超过限制")
                except ValueError:
                    raise HTTPException(status_code=400, detail="远程图片响应无效")

            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > MAX_REMOTE_IMAGE_BYTES:
                    raise HTTPException(status_code=400, detail="远程图片大小超过限制")
                chunks.append(chunk)

    content = b"".join(chunks)
    detected_mime = _infer_image_mime(content)
    header_mime = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    content_type = detected_mime or header_mime
    if content_type not in ALLOWED_REMOTE_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="不支持的远程图片类型")

    filename = urlparse(str(resp.url)).path.rsplit("/", 1)[-1] or "downloaded-image"
    if "." not in filename:
        ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(content_type, ".jpg")
        filename = f"{filename}{ext}"
    return content, filename, content_type
