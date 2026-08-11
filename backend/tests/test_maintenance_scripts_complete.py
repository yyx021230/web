from __future__ import annotations

import json
import sqlite3
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.session import async_session
from app.models.copywriting import Copywriting
from app.models.prompt import PromptCategory, PromptExample
from app.models.user import User
from app.models.xhs_account_note import XHSAccountNote
from app.models.xhs_environment import XHSEnvironment
from app.scripts import curate_xhs_notes_to_copywriting as curate_module
from app.scripts import import_ai_prompt_candidates as import_module
from app.scripts import retag_xhs_content_tags as retag_module
from app.scripts import sync_xhs_profile_stat as profile_module


def _candidate(index: int, *, account: str = "账号A", tag: str = "行情") -> curate_module.Candidate:
    content = (f"第{index}条完整汽车内容，包含价格、配置、体验和购买建议。" * 12) + f"#{tag}"
    return curate_module.Candidate(
        title=f"值得关注的汽车方案{index}",
        content=content,
        account_name=account,
        primary_tag=tag,
        secondary_tag="购车建议",
        published_at=datetime(2026, 8, 1),
        exact_key=f"exact-{index}",
        template_key=f"template-{index}",
    )


def test_curate_helpers_cover_validation_tags_and_round_robin(monkeypatch):
    assert curate_module._normalize(" A \n B ") == "ab"
    assert curate_module._exact_key("标题", "正文") == curate_module._exact_key("标 题", "正\n文")
    assert curate_module._template_key("6月优惠", "价格12.5万 #零跑[话题]") == curate_module._template_key(
        "7月优惠", "价格13万 #小鹏[话题]"
    )
    assert not curate_module._is_usable("短", "正文" * 100)
    assert not curate_module._is_usable("合格标题", "太短")
    assert not curate_module._is_usable("合格标题", "同步失败" + "有效内容" * 60)
    assert not curate_module._is_usable("合格标题", "啊" * 200)
    assert curate_module._is_usable(
        "完整汽车选购建议",
        "车型价格配置空间续航动力操控安全智能座舱售后保值优惠金融方案。" * 10,
    )

    monkeypatch.setattr(curate_module, "MAX_ITEMS_PER_ACCOUNT", 1)
    candidates = [
        _candidate(1, account="账号A", tag="行情"),
        _candidate(2, account="账号A", tag="行情"),
        _candidate(3, account="账号B", tag="测评"),
        _candidate(4, account="账号C", tag="测评"),
    ]
    duplicate_template = curate_module.Candidate(
        **{**candidates[0].__dict__, "title": "重复模板", "exact_key": "other"}
    )
    duplicate_template = curate_module.Candidate(
        **{**duplicate_template.__dict__, "template_key": candidates[0].template_key}
    )
    selected = curate_module._choose_candidates(candidates + [duplicate_template], limit=10)
    assert len(selected) == 3
    assert {item.account_name for item in selected} == {"账号A", "账号B", "账号C"}
    assert curate_module._quality_key(selected[0])[0] >= 0
    assert curate_module._source_tags(candidates[0])[-3:] == ["行情", "购车建议", "账号主页优选"]


@pytest.mark.asyncio
async def test_curate_imports_only_eligible_distinct_notes(client):
    content = "这是一篇结构完整的购车分析，覆盖价格配置空间续航以及真实使用建议。" * 8
    async with async_session() as db:
        db.add(User(id=1, username="admin", email="admin@example.com", hashed_password="x", role="admin"))
        db.add(XHSEnvironment(id=1, shop_id="env-1", account_name="账号A"))
        await db.flush()
        db.add(Copywriting(title="已有标题", content=content, tags=[], created_by=1))
        db.add_all(
            [
                XHSAccountNote(
                    environment_id=1,
                    feed_id="note-1",
                    account_name="账号A",
                    title="全新车型购买建议",
                    content=content + "新增差异内容一",
                    primary_content_tag="购车攻略",
                    secondary_content_tag="价格分析",
                    status="active",
                ),
                XHSAccountNote(
                    environment_id=1,
                    feed_id="note-2",
                    account_name="账号A",
                    title="无效",
                    content="太短",
                    status="active",
                ),
                XHSAccountNote(
                    environment_id=1,
                    feed_id="note-3",
                    account_name="账号A",
                    title="全新车型购买建议",
                    content=content + "新增差异内容一",
                    status="active",
                ),
                XHSAccountNote(
                    environment_id=1,
                    feed_id="note-4",
                    account_name="账号B",
                    title="离线内容不会导入",
                    content=content + "离线",
                    status="offline",
                ),
            ]
        )
        await db.commit()

    preview = await curate_module.curate(limit=10, dry_run=True)
    assert preview["source_notes"] == 3
    assert preview["selected"] == 1
    assert preview["skipped_invalid"] == 1
    assert preview["skipped_existing_or_exact_duplicate"] == 1
    saved = await curate_module.curate(limit=10, dry_run=False)
    assert saved["selected"] == 1
    async with async_session() as db:
        rows = (await db.execute(select(Copywriting))).scalars().all()
    assert len(rows) == 2
    imported = next(row for row in rows if row.title == "全新车型购买建议")
    assert "购车攻略" in imported.tags


@pytest.mark.asyncio
async def test_prompt_candidate_import_create_duplicate_and_dry_run(client, tmp_path):
    async with async_session() as db:
        db.add(User(id=1, username="admin", email="admin@example.com", hashed_password="x", role="admin"))
        await db.commit()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {"id": 1, "index": 7, "bucket": "汽车", "prompt": "  蓝色  汽车 ", "url": "https://img/1"},
                {"id": 2, "prompt": "蓝色 汽车", "url": "https://img/2"},
                {"id": 3, "prompt": "红色汽车", "url": "https://img/1"},
                {"id": 4, "prompt": "", "url": "https://img/4"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = await import_module.import_candidates(manifest, dry_run=False)
    assert result == {
        "source_count": 4,
        "imported": 1,
        "duplicate_prompt": 1,
        "duplicate_image": 1,
        "invalid": 1,
        "dry_run": False,
    }
    second = await import_module.import_candidates(manifest, dry_run=True)
    assert second["duplicate_prompt"] == 2
    assert second["duplicate_image"] == 1
    async with async_session() as db:
        assert len((await db.execute(select(PromptCategory))).scalars().all()) == 1
        example = (await db.execute(select(PromptExample))).scalar_one()
        assert example.name == "精选 007 · 汽车"
        assert example.chinese_example == "蓝色 汽车"

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        await import_module.import_candidates(invalid, dry_run=True)


def _create_retag_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        create table xhs_account_notes (
          id integer primary key, environment_id integer, status text,
          primary_content_tag text, secondary_content_tag text, account_name text,
          title text, content text, published_at text, post_url text,
          liked_count integer, collected_count integer, comment_count integer,
          detail_synced_at text, content_status text, updated_at text
        )
        """
    )
    conn.executemany(
        """insert into xhs_account_notes values
        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 2, 3, ?, ?, null)""",
        [
            (1, 8, "active", "", "", "账号A", "降价信息", "完整正文", "2026-08-01", "url1", "now", "from_detail"),
            (2, 9, "active", "旧", "标签", "账号B", "配置分析", "完整正文", "2026-08-02", "url2", "now", "from_detail"),
            (3, 8, "offline", "", "", "账号C", "离线", "完整正文", "", "url3", "now", "from_detail"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_retag_fetch_tag_retry_csv_and_writeback(monkeypatch, tmp_path):
    db_path = tmp_path / "notes.db"
    _create_retag_db(db_path)
    rows = retag_module.fetch_rows(db_path, limit=1, environment_id=8, status="active", retag_all=False)
    assert [row["id"] for row in rows] == [1]
    assert len(retag_module.fetch_rows(db_path, 0, 0, "", True)) == 3

    calls = 0

    async def tag_model(_client, _note):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("503 temporary")
        return "购车决策", "价格"

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(retag_module, "_tag_xhs_account_note_with_model", tag_model)
    monkeypatch.setattr(retag_module.asyncio, "sleep", no_sleep)
    tagged = await retag_module.tag_one(object(), rows[0], retag_module.asyncio.Semaphore(1))
    assert tagged["new_primary"] == "购车决策"
    assert tagged["changed"] == "yes"
    assert calls == 2

    async def permanent_failure(_client, _note):
        raise RuntimeError("invalid response")

    monkeypatch.setattr(retag_module, "_tag_xhs_account_note_with_model", permanent_failure)
    failed = await retag_module.tag_one(object(), rows[0], retag_module.asyncio.Semaphore(1))
    assert failed["error"] == "invalid response"

    output = tmp_path / "result" / "rows.csv"
    retag_module.write_csv(output, [tagged, failed])
    assert "购车决策" in output.read_text(encoding="utf-8-sig")
    empty = tmp_path / "empty.csv"
    retag_module.write_csv(empty, [])
    assert not empty.exists()
    retag_module.write_back(db_path, [tagged, failed])
    updated = retag_module.fetch_rows(db_path, 0, 8, "active", True)[0]
    assert updated["primary_content_tag"] == "购车决策"


@pytest.mark.asyncio
async def test_retag_run_empty_and_success_paths(monkeypatch, tmp_path, capsys):
    args = Namespace(
        db=str(tmp_path / "db.sqlite"),
        output=str(tmp_path / "all.csv"),
        failed_output=str(tmp_path / "failed.csv"),
        limit=0,
        concurrency=0,
        dry_run=True,
        all=False,
        environment_id=0,
        status="",
    )
    monkeypatch.setattr(retag_module, "parse_args", lambda: args)
    monkeypatch.setattr(retag_module, "fetch_rows", lambda *values: [])
    await retag_module.run()
    assert "eligible=0" in capsys.readouterr().out

    row = {
        "id": 1,
        "source": "model",
        "old_primary": "",
        "old_secondary": "",
        "new_primary": "测评",
        "new_secondary": "空间",
        "changed": "yes",
        "error": "",
        "account_name": "账号",
        "title": "标题",
        "published_at": "",
        "post_url": "",
    }
    monkeypatch.setattr(retag_module, "fetch_rows", lambda *values: [SimpleNamespace()])

    async def fake_tag(*_args):
        return row

    monkeypatch.setattr(retag_module, "tag_one", fake_tag)
    await retag_module.run()
    output = capsys.readouterr().out
    assert "final_success=1" in output
    assert "dry_run=true" in output


@pytest.mark.asyncio
async def test_profile_stat_script_parses_and_forwards_options(monkeypatch, capsys):
    args = Namespace(
        start_date="2026-08-01",
        end_date="2026-08-03",
        delay_seconds=0.5,
        limit_days=2,
        max_retries=4,
        no_skip_existing=True,
    )
    received = {}

    async def backfill(self, **kwargs):
        received.update(kwargs)
        return {"days": 2}

    monkeypatch.setattr(profile_module, "parse_args", lambda: args)
    monkeypatch.setattr(profile_module.XHSProfileStatService, "backfill", backfill)
    await profile_module.main()
    assert str(received["start_date"]) == "2026-08-01"
    assert str(received["end_date"]) == "2026-08-03"
    assert received["skip_existing"] is False
    assert "'days': 2" in capsys.readouterr().out
