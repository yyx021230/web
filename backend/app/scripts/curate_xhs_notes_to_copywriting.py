"""Curate reusable XHS account notes into the copywriting library.

The account-note table contains operational source data.  This script only
imports complete, structurally distinct samples and deliberately does not use
engagement metrics, because those metrics may be delayed or incomplete.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass

from sqlalchemy import select

from app.db.session import async_session
from app.models.copywriting import Copywriting
from app.models.xhs_account_note import XHSAccountNote
from app.services.copywriting_service import CopywritingService


MIN_CONTENT_LENGTH = 150
MAX_CONTENT_LENGTH = 4_000
MAX_ITEMS_PER_ACCOUNT = 24


@dataclass(frozen=True)
class Candidate:
    title: str
    content: str
    account_name: str
    primary_tag: str
    secondary_tag: str
    published_at: object
    exact_key: str
    template_key: str


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()


def _exact_key(title: str, content: str) -> str:
    return hashlib.sha256(_normalize(title + "\n" + content).encode("utf-8")).hexdigest()


def _template_key(title: str, content: str) -> str:
    """Collapse price/date/hashtag variants of the same copywriting template."""
    text = _normalize(title + "\n" + content)
    text = re.sub(r"#[^#\s]{1,50}(?:\[话题\])?", "#tag", text)
    text = re.sub(r"\d+(?:[.,，]\d+)?(?:万|w|km|k|元|%|期|月|年|v)?", "#", text)
    text = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_tags(candidate: Candidate) -> list[str]:
    tags = CopywritingService._extract_tags(candidate.content)
    for value in (candidate.primary_tag, candidate.secondary_tag, "账号主页优选"):
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return tags[:20]


def _is_usable(title: str, content: str) -> bool:
    if not title or len(title) < 6 or len(title) > 255:
        return False
    if len(content) < MIN_CONTENT_LENGTH or len(content) > MAX_CONTENT_LENGTH:
        return False
    normalized = _normalize(content)
    if len(set(normalized)) < 20:
        return False
    blocked_fragments = ("同步失败", "暂无内容", "内容不可见", "笔记已删除", "加载失败")
    return not any(fragment in content for fragment in blocked_fragments)


def _quality_key(candidate: Candidate) -> tuple[int, int, str]:
    """Content-only quality signal: complete but not unnecessarily long copy wins."""
    length = len(candidate.content)
    preferred_length_penalty = abs(length - 700)
    structure = sum(candidate.content.count(mark) for mark in "。！？；：\n")
    return (preferred_length_penalty, -structure, candidate.title)


def _choose_candidates(candidates: list[Candidate], *, limit: int) -> list[Candidate]:
    """Round-robin category and account samples so one account/template cannot dominate."""
    by_tag_and_account: dict[str, dict[str, list[Candidate]]] = defaultdict(lambda: defaultdict(list))
    for candidate in candidates:
        tag = candidate.primary_tag or "未标注"
        by_tag_and_account[tag][candidate.account_name or "未知账号"].append(candidate)

    tag_queues: dict[str, deque[deque[Candidate]]] = {}
    for tag, accounts in by_tag_and_account.items():
        account_queues = []
        for values in accounts.values():
            values.sort(key=_quality_key)
            account_queues.append(deque(values))
        account_queues.sort(key=lambda items: (-len(items), items[0].account_name if items else ""))
        tag_queues[tag] = deque(account_queues)

    selected: list[Candidate] = []
    selected_template_keys: set[str] = set()
    selected_per_account: dict[str, int] = defaultdict(int)
    tag_cycle = deque(sorted(tag_queues, key=lambda tag: (-sum(map(len, tag_queues[tag])), tag)))

    while tag_cycle and len(selected) < limit:
        tag = tag_cycle.popleft()
        account_queues = tag_queues[tag]
        chosen: Candidate | None = None
        attempts = len(account_queues)
        while attempts and account_queues:
            queue = account_queues.popleft()
            attempts -= 1
            while queue and (
                queue[0].template_key in selected_template_keys
                or selected_per_account[queue[0].account_name] >= MAX_ITEMS_PER_ACCOUNT
            ):
                queue.popleft()
            if queue:
                chosen = queue.popleft()
            if queue:
                account_queues.append(queue)
            if chosen:
                break

        if chosen:
            selected.append(chosen)
            selected_template_keys.add(chosen.template_key)
            selected_per_account[chosen.account_name] += 1

        if account_queues:
            tag_cycle.append(tag)

    return selected


async def curate(*, limit: int, dry_run: bool) -> dict[str, object]:
    async with async_session() as session:
        existing = (
            await session.execute(
                select(Copywriting.title, Copywriting.content).where(Copywriting.deleted_at.is_(None))
            )
        ).all()
        existing_exact_keys = {_exact_key(title or "", content or "") for title, content in existing}
        existing_template_keys = {_template_key(title or "", content or "") for title, content in existing}

        rows = (
            await session.execute(
                select(XHSAccountNote).where(XHSAccountNote.status == "active")
            )
        ).scalars().all()

        candidates: list[Candidate] = []
        skipped_invalid = 0
        skipped_existing = 0
        seen_exact: set[str] = set()
        for row in rows:
            title = str(row.title or "").strip()
            content = str(row.content or "").strip()
            if not _is_usable(title, content):
                skipped_invalid += 1
                continue
            exact_key = _exact_key(title, content)
            template_key = _template_key(title, content)
            if exact_key in seen_exact or exact_key in existing_exact_keys or template_key in existing_template_keys:
                skipped_existing += 1
                continue
            seen_exact.add(exact_key)
            candidates.append(
                Candidate(
                    title=title,
                    content=content,
                    account_name=str(row.account_name or row.profile_nickname or "未知账号").strip(),
                    primary_tag=str(row.primary_content_tag or "").strip(),
                    secondary_tag=str(row.secondary_content_tag or "").strip(),
                    published_at=row.published_at,
                    exact_key=exact_key,
                    template_key=template_key,
                )
            )

        selected = _choose_candidates(candidates, limit=limit)
        per_tag: dict[str, int] = defaultdict(int)
        per_account: dict[str, int] = defaultdict(int)
        for item in selected:
            per_tag[item.primary_tag or "未标注"] += 1
            per_account[item.account_name] += 1

        if not dry_run:
            for item in selected:
                session.add(
                    Copywriting(
                        title=item.title,
                        content=item.content,
                        tags=_source_tags(item),
                        category=CopywritingService._extract_category(item.title, item.content),
                        created_by=1,
                    )
                )
            await session.commit()
        else:
            await session.rollback()

    return {
        "source_notes": len(rows),
        "eligible_after_content_check": len(candidates),
        "selected": len(selected),
        "skipped_invalid": skipped_invalid,
        "skipped_existing_or_exact_duplicate": skipped_existing,
        "by_primary_tag": dict(sorted(per_tag.items(), key=lambda item: (-item[1], item[0]))),
        "distinct_accounts": len(per_account),
        "max_selected_per_account": max(per_account.values(), default=0),
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1_000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be positive")
    print(json.dumps(asyncio.run(curate(limit=args.limit, dry_run=args.dry_run)), ensure_ascii=False))


if __name__ == "__main__":
    main()
