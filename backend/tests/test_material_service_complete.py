"""Complete lifecycle contracts for the material service."""

import pytest

from app.db.session import async_session as session_factory
from app.services.material_service import MaterialService


@pytest.mark.asyncio
async def test_material_creation_listing_and_lookup(client):
    async with session_factory() as db:
        service = MaterialService(db)
        image = await service.create(
            "cover",
            "image",
            "/uploads/cover.png",
            width=768,
            height=1024,
            category="covers",
            tags=["cars"],
            file_size=123,
            user_id=1,
        )
        await service.create("other", "image", "data:image/png;base64,AA", category="other", user_id=2)
        design = await service.create_design(
            "design",
            {"objects": []},
            "data:image/png;base64,BB",
            900,
            1200,
            1,
        )
        template = await service.create_template(
            "template",
            "/uploads/template.png",
            {"prompt": "car"},
            768,
            1024,
            ["folder"],
            1,
        )
        draft = await service.create_ai_draft(
            "draft",
            "/uploads/draft.png",
            {"model": "gpt-image-2"},
            768,
            1024,
            1,
        )

        items, total = await service.get_list(page=1, limit=20, user_id=1, exclude_category="ai-template")
        category_items, category_total = await service.get_list(category="covers")

        assert total == 3
        assert {item.id for item in items} == {image.id, design.id, draft.id}
        assert category_total == 1
        assert category_items[0].id == image.id
        assert await service.get_by_id(image.id, user_id=1) is not None
        assert await service.get_by_id(image.id, user_id=2) is None
        assert template.category == "ai-template"
        assert draft.category is None


@pytest.mark.asyncio
async def test_update_design_enforces_ownership_and_updates_every_field(client):
    async with session_factory() as db:
        service = MaterialService(db)
        design = await service.create_design("old", {"v": 1}, "old", 1, 2, 7)

        assert await service.update_design(9999, name="missing", user_id=7) is None
        assert await service.update_design(design.id, name="blocked", user_id=8) is None

        updated = await service.update_design(
            design.id,
            name="new",
            design_json={"v": 2},
            thumbnail="new-thumb",
            width=100,
            height=200,
            tags=["ready"],
            user_id=7,
        )

        assert updated is not None
        assert (updated.name, updated.design_json, updated.url) == ("new", {"v": 2}, "new-thumb")
        assert (updated.width, updated.height, updated.tags) == (100, 200, ["ready"])


@pytest.mark.asyncio
async def test_delete_is_owner_scoped_and_storage_failures_are_non_fatal(client, monkeypatch):
    deleted_urls: list[str] = []

    async def delete_file(url: str) -> None:
        deleted_urls.append(url)
        if url.endswith("broken.png"):
            raise OSError("disk unavailable")

    monkeypatch.setattr("app.services.material_service.storage.delete", delete_file)

    async with session_factory() as db:
        service = MaterialService(db)
        owned = await service.create("owned", "image", "/uploads/owned.png", user_id=1)
        broken = await service.create("broken", "image", "/uploads/broken.png", user_id=1)
        inline = await service.create("inline", "image", "data:image/png;base64,AA", user_id=1)

        assert await service.delete(9999, user_id=1) is False
        assert await service.delete(owned.id, user_id=2) is False
        assert await service.delete(owned.id, user_id=1) is True
        assert await service.delete(broken.id, user_id=1) is True
        assert await service.delete(inline.id, user_id=1) is True
        assert deleted_urls == ["/uploads/owned.png", "/uploads/broken.png"]
        assert await service.get_by_id(owned.id, user_id=1) is None


@pytest.mark.asyncio
async def test_delete_all_usage_and_folder_operations(client, monkeypatch):
    deleted_urls: list[str] = []

    async def delete_file(url: str) -> None:
        deleted_urls.append(url)
        if "ignored" in url:
            raise OSError("ignored")

    monkeypatch.setattr("app.services.material_service.storage.delete", delete_file)

    async with session_factory() as db:
        service = MaterialService(db)
        first = await service.create(
            "first", "image", "/uploads/first.png", tags=["old", "keep"], file_size=10, user_id=5
        )
        second = await service.create(
            "second", "image", "data:image/png;base64,AA", tags=["old"], file_size=20, user_id=5
        )
        third = await service.create(
            "third", "image", "/uploads/ignored.png", tags=["other"], file_size=30, user_id=6
        )

        assert await service.get_storage_usage(5) == (30, 1, 2)
        assert await service.rename_folder("missing", "new", 5) == 0
        assert await service.rename_folder("old", "new", 5) == 2
        await db.refresh(first)
        await db.refresh(second)
        assert first.tags == ["new", "keep"]
        assert second.tags == ["new"]

        assert await service.delete_folder("missing", 5) == {"affected_count": 0, "moved_to_unclassified": 0}
        assert await service.delete_folder("new", 5) == {"affected_count": 2, "moved_to_unclassified": 2}

        assert await service.delete_all(user_id=5) == 2
        assert deleted_urls == ["/uploads/first.png"]
        assert await service.get_storage_usage(5) == (0, 0, 0)
        assert await service.delete_all() == 1
        assert deleted_urls[-1] == "/uploads/ignored.png"
        await db.refresh(third)
        assert third.deleted_at is not None
