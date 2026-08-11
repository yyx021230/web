from __future__ import annotations

import base64
import io
import json

import numpy as np
import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from pydantic import ValidationError
from starlette.datastructures import Headers

from app.api.v1.admin import car_models as module
from app.db.session import async_session
from app.models.user import User
from tests.conftest import make_auth_headers


def _png_bytes(color=(20, 30, 40), size=(20, 12)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(filename: str, content: bytes, content_type="image/png") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


async def _admin_headers():
    async with async_session() as db:
        user = User(username="admin", email="admin@example.com", hashed_password="x", role="admin")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return make_auth_headers(user.id)


def test_car_model_validation_filename_and_oss_helpers(monkeypatch):
    normalized = module._validate_data({
        " 零跑 ": {" C10 ": [{"label": " 正面 ", "url": " https://img/1.jpg "}]}
    })
    assert normalized == {"零跑": {"C10": [{"label": "正面", "url": "https://img/1.jpg"}]}}
    invalid_values = [
        [],
        {"": {}},
        {"零跑": []},
        {"零跑": {"": []}},
        {"零跑": {"C10": {}}},
        {"零跑": {"C10": ["bad"]}},
        {"零跑": {"C10": [{"label": "", "url": "x"}]}},
    ]
    for value in invalid_values:
        with pytest.raises(ValueError):
            module._validate_data(value)

    assert module.CarImageItem(label="正面", url=" /uploads/a.jpg ").url == "/uploads/a.jpg"
    assert module.CarImageItem(label="正面", url="https://img/a.jpg").url.startswith("https://")
    for url in ("", "ftp://img/a.jpg", "relative.jpg"):
        with pytest.raises(ValidationError):
            module.CarImageItem(label="正面", url=url)

    assert module._normalize_key(" A-B_C.jpg ") == "abcjpg"
    assert module._detect_angle("car-front.JPG") == "正前方"
    assert module._detect_angle("车型_斜后.png") == "斜后方"
    assert module._detect_angle("unknown.png") is None
    assert module._slugify("  C10 / 新款  ") == "C10-新款"
    assert module._slugify("///") == "car-model"
    assert module._guess_content_type("a.png", None) == "image/png"
    assert module._guess_content_type("a.unknown", "image/webp") == "image/webp"
    assert module._guess_content_type("a.unknown", "text/plain") == "image/jpeg"

    monkeypatch.setattr(module.settings, "car_model_oss_endpoint", "https://oss-cn.test.com")
    monkeypatch.setattr(module.settings, "car_model_oss_bucket", "bucket")
    assert module._car_model_oss_public_url("cars/a.jpg") == "https://bucket.oss-cn.test.com/cars/a.jpg"
    assert module._car_model_oss_key_from_url("http://bucket.oss-cn.test.com/cars/a.jpg") == "cars/a.jpg"
    assert module._car_model_oss_key_from_url("https://other/a.jpg") is None

    monkeypatch.setattr(module.settings, "car_model_oss_access_key_id", "")
    monkeypatch.setattr(module.settings, "car_model_oss_access_key_secret", "")
    with pytest.raises(HTTPException, match="OSS"):
        module._get_car_model_oss_bucket()
    monkeypatch.setattr(module.settings, "car_model_oss_access_key_id", "id")
    monkeypatch.setattr(module.settings, "car_model_oss_access_key_secret", "secret")
    monkeypatch.setattr(module.oss2, "Auth", lambda key, secret: (key, secret))
    monkeypatch.setattr(module.oss2, "Bucket", lambda auth, endpoint, bucket: (auth, endpoint, bucket))
    assert module._get_car_model_oss_bucket()[2] == "bucket"


@pytest.mark.asyncio
async def test_image_validation_ocr_clean_and_gpt_paths(monkeypatch):
    content = _png_bytes()
    image = module._validate_image_bytes("car.png", content)
    assert image.mode == "RGB"
    with pytest.raises(HTTPException, match="无法解析"):
        module._validate_image_bytes("bad.png", b"not-image")

    assert module._left_extend_for_filename("正前.png") == 44
    assert module._left_extend_for_filename("侧面.png") == 24
    boxes = module._watermark_bboxes(
        [
            {"text": "易车", "bbox": (1, 1, 5, 5)},
            {"text": "其他", "bbox": (2, 2, 4, 4)},
            {"text": "懂车帝", "bbox": [1, 1, 2, 2]},
        ],
        ["易车", "懂车帝"],
    )
    assert boxes == [(1, 1, 5, 5)]
    erased = module._erase_watermark_with_fill(image, boxes, filename="正前.png", dilate_pixels=1)
    assert tuple(np.array(erased)[1, 1]) == (255, 255, 255)

    async def no_ocr(_image):
        return []

    monkeypatch.setattr(module, "_baidu_ocr_detect", no_ocr)
    assert await module._clean_with_ocr(content, filename="侧面.png") == content

    async def with_ocr(_image):
        return [{"text": "易车", "bbox": (1, 1, 5, 5)}]

    monkeypatch.setattr(module, "_baidu_ocr_detect", with_ocr)
    cleaned = await module._clean_with_ocr(content, filename="正前.png")
    assert cleaned.startswith(b"\x89PNG")

    class _Adapter:
        result = {"image_urls": [f"data:image/png;base64,{base64.b64encode(content).decode()}"]}

        async def generate_image(self, **kwargs):
            assert kwargs["width"] == 20
            assert kwargs["height"] == 12
            return self.result

    monkeypatch.setattr(module, "GPTImage2Adapter", _Adapter)
    assert await module._clean_with_gpt_image2(content, filename="a.png", content_type="image/png") == content
    _Adapter.result = {"image_urls": [], "error": "no result"}
    with pytest.raises(HTTPException, match="no result"):
        await module._clean_with_gpt_image2(content, filename="a.png", content_type="image/png")


@pytest.mark.asyncio
async def test_collect_import_files_and_storage_helpers(monkeypatch):
    content = _png_bytes()
    files = [
        _upload("", content),
        _upload("readme.txt", b"text", "text/plain"),
        _upload("unknown.png", content),
        _upload("正前.png", b""),
        _upload("侧面.png", content),
    ]
    by_angle, warnings = await module._collect_import_files(files)
    assert list(by_angle) == ["侧面"]
    assert len(warnings) == 3
    with pytest.raises(HTTPException, match="重复角度"):
        await module._collect_import_files([_upload("侧面1.png", content), _upload("侧面2.png", content)])
    with pytest.raises(HTTPException, match="未识别到"):
        await module._collect_import_files([_upload("unknown.png", content)])
    assert module._ordered_images({
        "侧面": {"label": "侧面", "url": "2"},
        "正前方": {"label": "正前方", "url": "1"},
    }) == [{"label": "正前方", "url": "1"}, {"label": "侧面", "url": "2"}]

    class _Bucket:
        def __init__(self):
            self.put = None
            self.deleted = None

        def put_object(self, key, body, headers=None):
            self.put = (key, body, headers)

        def delete_object(self, key):
            self.deleted = key

    bucket = _Bucket()
    monkeypatch.setattr(module.settings, "car_model_oss_endpoint", "https://oss.test")
    monkeypatch.setattr(module.settings, "car_model_oss_bucket", "bucket")
    url = await module._upload_car_model_to_oss(
        bucket=bucket,
        object_key="cars/a.png",
        content=content,
        content_type="image/png",
    )
    assert url.endswith("/cars/a.png")
    assert bucket.put[2] == {"Content-Type": "image/png"}
    await module._delete_car_model_oss_object(bucket, "cars/a.png")
    assert bucket.deleted == "cars/a.png"


@pytest.mark.asyncio
async def test_car_model_admin_crud_replace_and_export(client, monkeypatch):
    headers = await _admin_headers()
    payload = {
        "零跑": {
            "C10": [
                {"label": "正前方", "url": "https://img/1.jpg"},
                {"label": "侧面", "url": "https://img/2.jpg"},
            ]
        }
    }
    invalid_ext = await client.post(
        "/api/v1/admin/car-models/replace",
        files={"file": ("cars.txt", b"{}", "text/plain")},
        headers=headers,
    )
    assert invalid_ext.status_code == 400
    empty = await client.post(
        "/api/v1/admin/car-models/replace",
        files={"file": ("cars.json", b"", "application/json")},
        headers=headers,
    )
    assert empty.status_code == 400
    malformed = await client.post(
        "/api/v1/admin/car-models/replace",
        files={"file": ("cars.json", b"{", "application/json")},
        headers=headers,
    )
    assert malformed.status_code == 400
    replaced = await client.post(
        "/api/v1/admin/car-models/replace",
        files={"file": ("cars.json", json.dumps(payload, ensure_ascii=False).encode(), "application/json")},
        headers=headers,
    )
    assert replaced.status_code == 200
    assert replaced.json()["data"]["models"] == 1
    all_models = await client.get("/api/v1/admin/car-models/all", headers=headers)
    assert all_models.json()["data"] == payload
    exported = await client.get("/api/v1/admin/car-models/export", headers=headers)
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]

    missing_update = await client.put(
        "/api/v1/admin/car-models/model",
        json={"brand": "零跑", "model": "C11", "images": [{"label": "正面", "url": "https://img/x.jpg"}]},
        headers=headers,
    )
    assert missing_update.status_code == 404
    updated = await client.put(
        "/api/v1/admin/car-models/model",
        json={"brand": "零跑", "model": "C10", "images": [
            {"label": "正面", "url": "https://img/new.jpg"},
            {"label": "侧面", "url": "https://img/side.jpg"},
        ]},
        headers=headers,
    )
    assert updated.status_code == 200

    deleted_urls = []

    async def fake_delete(url):
        deleted_urls.append(url)

    monkeypatch.setattr(module, "_delete_storage_url_if_possible", fake_delete)
    image_deleted = await client.request(
        "DELETE",
        "/api/v1/admin/car-models/model/image",
        json={"brand": "零跑", "model": "C10", "label": "正面", "url": "https://img/new.jpg"},
        headers=headers,
    )
    assert image_deleted.status_code == 200
    assert deleted_urls == ["https://img/new.jpg"]
    last = await client.request(
        "DELETE",
        "/api/v1/admin/car-models/model/image",
        json={"brand": "零跑", "model": "C10", "label": "侧面", "url": "https://img/side.jpg"},
        headers=headers,
    )
    assert last.status_code == 400
    missing_brand = await client.request(
        "DELETE",
        "/api/v1/admin/car-models/model",
        json={"brand": "不存在", "model": "C10"},
        headers=headers,
    )
    assert missing_brand.status_code == 404
    deleted = await client.request(
        "DELETE",
        "/api/v1/admin/car-models/model",
        json={"brand": "零跑", "model": "C10"},
        headers=headers,
    )
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_car_model_folder_import_paths(client, monkeypatch):
    headers = await _admin_headers()
    content = _png_bytes()
    assert (
        await client.post(
            "/api/v1/admin/car-models/import-folder",
            data={"brand": " ", "model": "C10", "already_cleaned": "true"},
            files=[("files", ("正前.png", content, "image/png"))],
            headers=headers,
        )
    ).status_code == 400
    assert (
        await client.post(
            "/api/v1/admin/car-models/import-folder",
            data={"brand": "零跑", "model": "C10", "already_cleaned": "false", "clean_method": "bad"},
            files=[("files", ("正前.png", content, "image/png"))],
            headers=headers,
        )
    ).status_code == 400

    monkeypatch.setattr(module, "_get_car_model_oss_bucket", lambda: object())

    async def fake_upload(**kwargs):
        return f"https://oss/{kwargs['object_key']}"

    monkeypatch.setattr(module, "_upload_car_model_to_oss", fake_upload)
    imported = await client.post(
        "/api/v1/admin/car-models/import-folder",
        data={
            "brand": "零跑",
            "model": "C10",
            "already_cleaned": "true",
            "clean_method": "ocr",
            "overwrite": "false",
        },
        files=[
            ("files", ("正前.png", content, "image/png")),
            ("files", ("侧面.png", content, "image/png")),
        ],
        headers=headers,
    )
    assert imported.status_code == 200
    assert imported.json()["data"]["imported_angles"] == ["正前方", "侧面"]
    assert imported.json()["data"]["clean_method"] is None
    duplicate = await client.post(
        "/api/v1/admin/car-models/import-folder",
        data={"brand": "零跑", "model": "C10", "already_cleaned": "true", "overwrite": "false"},
        files=[("files", ("正前.png", content, "image/png"))],
        headers=headers,
    )
    assert duplicate.status_code == 400
    overwrite = await client.post(
        "/api/v1/admin/car-models/import-folder",
        data={"brand": "零跑", "model": "C10", "already_cleaned": "true", "overwrite": "true"},
        files=[("files", ("正后.png", content, "image/png"))],
        headers=headers,
    )
    assert overwrite.status_code == 200
