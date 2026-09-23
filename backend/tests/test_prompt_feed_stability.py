import pytest
from PIL import Image

from app.services.prompt_image_metadata import add_prompt_image_dimensions, _dimensions
from tests.conftest import make_auth_headers
from tests.test_prompt_api_complete import _seed_prompt_users


def test_local_metadata_preserves_dimensions_caches_headers_and_handles_bad_files(tmp_path, monkeypatch):
    image_path = tmp_path / "cover.png"
    Image.new("RGB", (240, 160)).save(image_path)
    (tmp_path / "broken.png").write_bytes(b"not an image")
    items = [
        {"image_url": "/uploads/cover.png"},
        {"image_url": "/uploads/missing.png"},
        {"image_url": "/uploads/broken.png"},
        {"image_url": "https://example.com/cover.png"},
        {"image_url": "/uploads/%2e%2e/secret.png"},
        {"image_url": "http://[malformed"},
    ]
    _dimensions.cache_clear()
    add_prompt_image_dimensions(items, str(tmp_path))
    assert items[0]["image_width"] == 240
    assert items[0]["image_height"] == 160
    assert all("image_width" not in item for item in items[1:])

    def unexpected_open(*args, **kwargs):
        raise AssertionError("unchanged image header should be cached")
    monkeypatch.setattr(Image, "open", unexpected_open)
    add_prompt_image_dimensions(items[:1], str(tmp_path))
    assert _dimensions.cache_info().hits == 1


def test_metadata_honors_exif_orientation(tmp_path):
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (240, 160)).save(tmp_path / "rotated.jpg", exif=exif)
    items = [{"image_url": "/uploads/rotated.jpg"}]
    add_prompt_image_dimensions(items, str(tmp_path))
    assert (items[0]["image_width"], items[0]["image_height"]) == (160, 240)


def test_metadata_cache_invalidates_when_the_file_changes(tmp_path):
    path = tmp_path / "cover.png"
    items = [{"image_url": "/uploads/cover.png"}]
    Image.new("RGB", (100, 100)).save(path)
    add_prompt_image_dimensions(items, str(tmp_path))
    Image.new("RGB", (160, 240)).save(path)
    add_prompt_image_dimensions(items, str(tmp_path))
    assert (items[0]["image_width"], items[0]["image_height"]) == (160, 240)


@pytest.mark.asyncio
async def test_discovery_cursor_does_not_skip_after_deleting_loaded_rows_or_the_anchor(client):
    await _seed_prompt_users()
    headers = make_auth_headers(2)
    ids = []
    for index in range(12):
        response = await client.post("/api/v1/prompts", headers=headers,
                                     json={"name": f"cover-{index}", "chinese": f"prompt-{index}"})
        ids.append(response.json()["data"]["id"])

    params = {"random_seed": 123, "limit": 4}
    first = (await client.get("/api/v1/prompts", params=params)).json()["data"]
    visible = [item["id"] for item in first["items"]]
    anchor = first["next_cursor"]
    assert anchor == visible[-1]
    removed = {visible[0], anchor}
    for item_id in removed:
        assert (await client.delete(f"/api/v1/prompts/{item_id}", headers=headers)).status_code == 200

    all_remaining = [item_id for item_id in visible if item_id not in removed]
    for page in (2, 3):
        data = (await client.get("/api/v1/prompts", params={**params, "page": page, "after_id": anchor})).json()["data"]
        all_remaining.extend(item["id"] for item in data["items"])
        anchor = data["next_cursor"]
    assert data["has_more"] is False
    assert anchor is None
    assert len(all_remaining) == 10
    assert set(all_remaining) == set(ids) - removed
    assert (await client.get("/api/v1/prompts", params={"after_id": 1})).status_code == 400


@pytest.mark.asyncio
async def test_feed_includes_cover_dimensions_without_database_migrations(client, tmp_path, monkeypatch):
    from app.api.v1 import prompts
    await _seed_prompt_users()
    monkeypatch.setattr(prompts.settings, "storage_path", str(tmp_path))
    Image.new("RGB", (160, 240)).save(tmp_path / "portrait.webp")
    await client.post("/api/v1/prompts", headers=make_auth_headers(2), json={
        "chinese": "sized cover", "image_url": "/uploads/portrait.webp",
    })
    response = await client.get("/api/v1/prompts", params={"random_seed": 123})
    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert (item["image_width"], item["image_height"]) == (160, 240)
    ordinary_list = await client.get("/api/v1/prompts", params={"category": "未分类"})
    assert "image_width" not in ordinary_list.json()["data"]["items"][0]
