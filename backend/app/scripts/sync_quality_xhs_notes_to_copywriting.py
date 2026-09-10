"""Sync complete, distinct high-quality XHS notes into the copywriting library.

The script is intentionally idempotent. It treats copies that only change
dates, prices, or hashtags as one template and keeps the strongest source note.
Run without ``--apply`` to preview the transaction.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select

from app.db.session import async_session
from app.models.copywriting import Copywriting
from app.models.xhs_account_note import XHSAccountNote
from app.services.copywriting_service import CopywritingService


MIN_CONTENT_LENGTH = 150
MAX_CONTENT_LENGTH = 4_000
DEFAULT_PUBLISHED_AFTER = datetime(2026, 3, 1)


@dataclass(frozen=True)
class Candidate:
    note_id: int
    title: str
    content: str
    account_name: str
    primary_tag: str
    secondary_tag: str
    view_count: int
    comment_count: int
    published_at: datetime | None
    exact_key: str
    template_key: str


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()


def _exact_key(title: str, content: str) -> str:
    value = _normalize(f"{title}\n{content}")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _template_key(title: str, content: str) -> str:
    value = _normalize(f"{title}\n{content}")
    value = re.sub(r"#[^#\s]{1,50}(?:\[话题\])?", "#tag", value)
    value = re.sub(r"\d+(?:[.,，]\d+)?(?:万|w|km|k|元|%|期|月|年|v)?", "#", value)
    value = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _invalid_reason(title: str, content: str) -> str | None:
    if not title or len(title) < 6 or len(title) > 255:
        return "invalid_title"
    if not content:
        return "missing_content"
    if len(content) < MIN_CONTENT_LENGTH:
        return "content_too_short"
    if len(content) > MAX_CONTENT_LENGTH:
        return "content_too_long"
    if len(set(_normalize(content))) < 20:
        return "low_information_content"
    blocked = ("同步失败", "暂无内容", "内容不可见", "笔记已删除", "加载失败")
    if any(fragment in content for fragment in blocked):
        return "blocked_content"
    return None


def _candidate_rank(candidate: Candidate) -> tuple[int, int, int, float]:
    """Prefer reach, then discussion, then a complete but manageable body."""
    timestamp = candidate.published_at.timestamp() if candidate.published_at else 0.0
    return (
        candidate.view_count,
        candidate.comment_count,
        -abs(len(candidate.content) - 700),
        timestamp,
    )


def _source_tags(candidate: Candidate) -> list[str]:
    tags = CopywritingService._extract_tags(candidate.content)
    for value in (
        candidate.primary_tag,
        candidate.secondary_tag,
        "优质帖子",
        "账号主页优选",
        f"来源账号:{candidate.account_name}",
    ):
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return tags[:20]


async def sync_quality_notes(*, apply: bool, published_after: datetime) -> dict[str, object]:
    async with async_session() as session:
        existing_rows = (
            await session.execute(
                select(Copywriting.title, Copywriting.content).where(Copywriting.deleted_at.is_(None))
            )
        ).all()
        existing_exact = {_exact_key(title or "", content or "") for title, content in existing_rows}
        existing_templates = {_template_key(title or "", content or "") for title, content in existing_rows}

        source_rows = (
            await session.execute(
                select(XHSAccountNote).where(
                    XHSAccountNote.status == "active",
                    XHSAccountNote.published_at >= published_after,
                    or_(XHSAccountNote.view_count >= 4_000, XHSAccountNote.comment_count >= 30),
                )
            )
        ).scalars().all()

        invalid_reasons: Counter[str] = Counter()
        represented_exact = 0
        represented_template = 0
        duplicate_exact = 0
        duplicate_template = 0
        seen_exact: set[str] = set()
        best_by_template: dict[str, Candidate] = {}

        for row in source_rows:
            title = str(row.title or "").strip()
            content = str(row.content or "").strip()
            reason = _invalid_reason(title, content)
            if reason:
                invalid_reasons[reason] += 1
                continue

            exact_key = _exact_key(title, content)
            template_key = _template_key(title, content)
            if exact_key in existing_exact:
                represented_exact += 1
                continue
            if template_key in existing_templates:
                represented_template += 1
                continue
            if exact_key in seen_exact:
                duplicate_exact += 1
                continue
            seen_exact.add(exact_key)

            candidate = Candidate(
                note_id=row.id,
                title=title,
                content=content,
                account_name=str(row.account_name or row.profile_nickname or "未知账号").strip(),
                primary_tag=str(row.primary_content_tag or "").strip(),
                secondary_tag=str(row.secondary_content_tag or "").strip(),
                view_count=int(row.view_count or 0),
                comment_count=int(row.comment_count or 0),
                published_at=row.published_at,
                exact_key=exact_key,
                template_key=template_key,
            )
            current = best_by_template.get(template_key)
            if current is None or _candidate_rank(candidate) > _candidate_rank(current):
                if current is not None:
                    duplicate_template += 1
                best_by_template[template_key] = candidate
            else:
                duplicate_template += 1

        selected = sorted(best_by_template.values(), key=_candidate_rank, reverse=True)
        per_tag: Counter[str] = Counter(item.primary_tag or "未标注" for item in selected)
        per_account: Counter[str] = Counter(item.account_name for item in selected)

        if apply:
            session.add_all(
                [
                    Copywriting(
                        title=item.title,
                        content=item.content,
                        tags=_source_tags(item),
                        category=CopywritingService._extract_category(item.title, item.content),
                        created_by=1,
                    )
                    for item in selected
                ]
            )
            await session.commit()
        else:
            await session.rollback()

        return {
            "published_after": published_after.isoformat(),
            "quality_source_notes": len(source_rows),
            "existing_copywritings": len(existing_rows),
            "already_represented_exact": represented_exact,
            "already_represented_by_template": represented_template,
            "skipped_invalid": sum(invalid_reasons.values()),
            "invalid_reasons": dict(sorted(invalid_reasons.items())),
            "duplicate_exact_in_source": duplicate_exact,
            "duplicate_template_in_source": duplicate_template,
            "inserted" if apply else "would_insert": len(selected),
            "distinct_source_accounts": len(per_account),
            "by_primary_tag": dict(per_tag.most_common()),
            "top_source_accounts": dict(per_account.most_common(20)),
            "applied": apply,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit missing templates to the library")
    parser.add_argument(
        "--published-after",
        type=datetime.fromisoformat,
        default=DEFAULT_PUBLISHED_AFTER,
        help="Inclusive source publish time in ISO format",
    )
    args = parser.parse_args()
    report = asyncio.run(sync_quality_notes(apply=args.apply, published_after=args.published_after))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
