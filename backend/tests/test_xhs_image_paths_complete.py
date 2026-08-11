"""Image localization and publish-path contracts for XHS automation."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.db.session import async_session
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.services import xhs_service as module
from app.services.xhs_service import XHSService


class _Response:
    def __init__(self, content: bytes = b"image", content_type: str = "image/png", fail: bool = False):
        self.content = content
        self.headers = {"content-type": content_type}
        self._fail = fail

    def raise_for_status(self):
        if self._fail:
            raise RuntimeError("download failed")


class _HttpClient:
    response = _Response()

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        return self.response


def test_image_extension_data_url_and_storage_path_guards(monkeypatch, tmp_path):
    storage_root = tmp_path / "uploads"
    storage_root.mkdir()
    monkeypatch.setattr(settings, "storage_path", str(storage_root))

    expected = {
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/jpeg": ".jpg",
    }
    for content_type, extension in expected.items():
        assert XHSService._guess_remote_image_extension("https://x.test/noext", content_type=content_type) == extension
    assert XHSService._guess_remote_image_extension("https://x.test/a.jpeg") == ".jpg"
    assert XHSService._guess_remote_image_extension("https://x.test/a.webp?x=1") == ".webp"
    assert XHSService._guess_remote_image_extension("https://x.test/a.unknown") == ".jpg"

    image = storage_root / "xhs" / "a.png"
    image.parent.mkdir()
    image.write_bytes(b"png")
    assert XHSService.local_upload_path_to_url(str(image)) == "/uploads/xhs/a.png"
    with pytest.raises(ValueError, match="uploads"):
        XHSService.local_upload_path_to_url(str(tmp_path / "outside.png"))
    assert XHSService._uploads_url_to_local_path("/uploads/xhs/a.png?token=1#x") == str(image.resolve())
    with pytest.raises(ValueError, match="非法"):
        XHSService._uploads_url_to_local_path("/uploads/../secret")

    encoded = base64.b64encode(b"hello").decode()
    assert XHSService._decode_data_image_url(f"data:image/png;base64,{encoded}") == (b"hello", ".png")
    assert XHSService._decode_data_image_url(f"data:image/avif;base64,{encoded}") == (b"hello", ".jpg")
    assert XHSService._decode_data_image_url("not-data") is None
    assert XHSService._decode_data_image_url("data:image/png;base64,a") is None


@pytest.mark.asyncio
async def test_publish_image_resolution_all_source_types(monkeypatch, tmp_path):
    storage_root = tmp_path / "uploads"
    local = storage_root / "library" / "local.png"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"local")
    relative = tmp_path / "relative.jpg"
    relative.write_bytes(b"relative")
    monkeypatch.setattr(settings, "storage_path", str(storage_root))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "XHS_HOST_UPLOAD_ROOT", "")
    monkeypatch.setattr(module, "UPLOADS_PUBLIC_BASE_URL", "")
    service = XHSService(None)  # type: ignore[arg-type]
    service.save_upload_image = AsyncMock(side_effect=lambda content, filename: str(storage_root / "xhs" / filename))

    assert await service._resolve_single_publish_image("/uploads/library/local.png") == str(local.resolve())
    assert await service._resolve_single_publish_image(str(relative)) == str(relative.resolve())
    assert await service._resolve_single_publish_image(f"file://{relative}") == str(relative.resolve())
    data_path = await service._resolve_single_publish_image(
        "data:image/webp;base64," + base64.b64encode(b"webp").decode()
    )
    assert data_path.endswith(".webp")

    monkeypatch.setattr(module.httpx, "AsyncClient", _HttpClient)
    remote_path = await service._resolve_single_publish_image("https://images.test/a.png")
    assert remote_path.endswith(".png")
    relative_path = await service._resolve_single_publish_image("relative.jpg")
    assert relative_path == str(relative.resolve())

    resolved = await service._resolve_publish_image_paths(
        ["", "/uploads/library/local.png", str(relative)]
    )
    assert resolved == [str(local.resolve()), str(relative.resolve())]
    with pytest.raises(ValueError, match="至少上传"):
        await service._resolve_publish_image_paths(["", " "])

    with pytest.raises(ValueError, match="文件不存在"):
        await service._resolve_single_publish_image(str(tmp_path / "missing.png"))
    with pytest.raises(ValueError, match="file://"):
        await service._resolve_single_publish_image(f"file://{tmp_path / 'missing.png'}")
    with pytest.raises(ValueError, match="格式无效"):
        await service._resolve_single_publish_image("data:image/png;base64,a")
    with pytest.raises(ValueError, match="不支持"):
        await service._resolve_single_publish_image("missing-relative.jpg")

    _HttpClient.response = _Response(fail=True)
    with pytest.raises(ValueError, match="下载图库远程图片失败"):
        await service._resolve_single_publish_image("https://images.test/fail.png")


@pytest.mark.asyncio
async def test_shared_upload_fallback_mapping_cover_persistence_and_download(monkeypatch, tmp_path):
    storage_root = tmp_path / "uploads"
    storage_root.mkdir()
    monkeypatch.setattr(settings, "storage_path", str(storage_root))
    service = XHSService(None)  # type: ignore[arg-type]
    service.save_upload_image = AsyncMock(return_value=str(storage_root / "xhs" / "saved.png"))

    monkeypatch.setattr(module, "UPLOADS_PUBLIC_BASE_URL", "https://shared.test")
    monkeypatch.setattr(module.httpx, "AsyncClient", _HttpClient)
    _HttpClient.response = _Response(content=b"shared", content_type="image/webp")
    shared = await service._resolve_single_publish_image("/uploads/shared/missing.webp")
    assert shared.endswith("saved.png")

    _HttpClient.response = _Response(fail=True)
    with pytest.raises(ValueError, match="回源下载失败"):
        await service._resolve_single_publish_image("/uploads/shared/missing.webp")
    monkeypatch.setattr(module, "UPLOADS_PUBLIC_BASE_URL", "")
    with pytest.raises(ValueError, match="图库图片文件不存在"):
        await service._resolve_single_publish_image("/uploads/shared/missing.webp")

    monkeypatch.setattr(module, "XHS_HOST_UPLOAD_ROOT", "C:/web/uploads")
    inside = storage_root / "xhs" / "mapped.png"
    assert XHSService._map_publish_path_for_external_browser(str(inside)).endswith("xhs/mapped.png")
    assert XHSService._map_publish_path_for_external_browser(str(tmp_path / "outside.png")) == str(tmp_path / "outside.png")
    monkeypatch.setattr(module, "XHS_HOST_UPLOAD_ROOT", "")
    assert XHSService._map_publish_path_for_external_browser(str(inside)) == str(inside)

    local_cover = storage_root / "covers" / "existing.png"
    local_cover.parent.mkdir()
    local_cover.write_bytes(b"cover")
    local_url = "/uploads/covers/existing.png"
    assert XHSService._is_existing_upload_url_available(local_url) is True
    assert XHSService._is_existing_upload_url_available("https://x.test/a.png") is False
    assert await service._persist_account_note_cover_image(None, existing_url=local_url) == local_url
    assert await service._persist_account_note_cover_image(None, existing_url="") is None
    assert await service._persist_account_note_cover_image(local_url) == local_url
    assert await service._persist_account_note_cover_image("relative.png") == "relative.png"
    service._download_account_note_cover_to_local = AsyncMock(return_value="/uploads/covers/downloaded.png")
    assert await service._persist_account_note_cover_image("https://x.test/cover.png", feed_id="feed") == "/uploads/covers/downloaded.png"
    service._download_account_note_cover_to_local.side_effect = RuntimeError("down")
    assert await service._persist_account_note_cover_image("https://x.test/fail.png") == "https://x.test/fail.png"

    assert service._prepare_account_note_cover_image(None, existing_url=local_url) == (local_url, None)
    assert service._prepare_account_note_cover_image(None, existing_url="") == (None, None)
    assert service._prepare_account_note_cover_image(local_url) == (local_url, None)
    assert service._prepare_account_note_cover_image("https://x.test/a.png") == (
        "https://x.test/a.png",
        "https://x.test/a.png",
    )
    assert service._prepare_account_note_cover_image("relative.png") == ("relative.png", None)

    service._download_account_note_cover_to_local = XHSService._download_account_note_cover_to_local.__get__(service)
    service.save_upload_image = AsyncMock(return_value=str(storage_root / "xhs" / "download.png"))
    _HttpClient.response = _Response(content=b"download", content_type="image/gif")
    downloaded = await service._download_account_note_cover_to_local(
        "https://images.test/cover",
        feed_id="feed:/unsafe",
    )
    assert downloaded == "/uploads/xhs/download.png"
    _HttpClient.response = _Response(content=b"", content_type="image/png")
    with pytest.raises(ValueError, match="响应为空"):
        await service._download_account_note_cover_to_local("https://images.test/empty")


@pytest.mark.asyncio
async def test_pending_cover_localizations_update_once(client):
    _ = client
    async with async_session() as db:
        db.add(XHSEnvironment(id=801, shop_id="shop-801", account_name="封面账号", status="active"))
        await db.flush()
        db.add(
            XHSAccountNote(
                environment_id=801,
                account_name="封面账号",
                feed_id="feed-cover",
                title="封面帖子",
                cover_image_url="https://old.test/cover.png",
            )
        )
        await db.commit()

    async with async_session() as db:
        service = XHSService(db)
        service._persist_account_note_cover_image = AsyncMock(return_value="/uploads/covers/new.png")
        await service._apply_pending_account_note_cover_localizations([])
        await service._apply_pending_account_note_cover_localizations(
            [
                (0, "bad", None, "https://x.test/bad.png"),
                (801, "", None, "https://x.test/bad.png"),
                (801, "feed-cover", "https://old.test/cover.png", "https://x.test/new.png"),
                (801, "feed-cover", "https://old.test/cover.png", "https://x.test/new.png"),
            ]
        )
        note = (
            await db.execute(
                module.select(XHSAccountNote).where(XHSAccountNote.feed_id == "feed-cover")
            )
        ).scalar_one()
        assert note.cover_image_url == "/uploads/covers/new.png"
        service._persist_account_note_cover_image.assert_awaited_once()
