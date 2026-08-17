from pydantic import BaseModel, Field, field_serializer, field_validator
from typing import Any, Optional
from datetime import datetime
from app.utils.timezone import utc_naive_to_aware_iso


# --- Environment ---

class EnvironmentOut(BaseModel):
    id: int
    shop_id: str
    account_name: str
    profile_url: Optional[str] = None
    sync_cloud_session_id: Optional[str] = None
    sync_cloud_api_key: Optional[str] = None
    sync_cloud_update_config: Optional[str] = None
    sync_browser_start_config: Optional[str] = None
    xhs_account_id: Optional[str] = None
    login_phone_number: Optional[str] = None
    is_sync_runner: bool = False
    notes: Optional[str] = None
    proxy_info: Optional[str] = None
    group_name: Optional[str] = None
    labels: Optional[str] = None
    department: str = "xhs"
    status: str

    model_config = {"from_attributes": True}


# --- Publish ---

class PublishRequest(BaseModel):
    environment_id: int
    title: str
    content: str
    image_paths: list[str]
    tags: list[str] = Field(default_factory=list)
    ai_origin_type: str = "manual"
    is_original: bool = False
    visibility: str = "公开可见"
    scheduled_at: Optional[datetime] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("标题不能为空")
        if len(title) > 20:
            raise ValueError("标题不能超过20字")
        return title

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("正文不能为空")
        if len(content) > 1000:
            raise ValueError("正文不能超过1000字")
        return content

    @field_validator("image_paths")
    @classmethod
    def validate_image_paths(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("请至少上传1张图片")
        normalized: list[str] = []
        for item in value:
            path = item.strip()
            if not path:
                raise ValueError("图片路径不能为空")
            normalized.append(path)
        return normalized

    @field_validator("ai_origin_type")
    @classmethod
    def validate_ai_origin_type(cls, value: str) -> str:
        allowed = {"manual", "text_ai", "image_ai", "all_ai"}
        normalized = (value or "manual").strip()
        if normalized not in allowed:
            raise ValueError("AI 标记无效")
        return normalized


class PublishOut(BaseModel):
    post_id: int
    feed_id: Optional[str] = None
    status: str
    scheduled_at: Optional[datetime] = None

    @field_serializer("scheduled_at")
    def serialize_scheduled_at(self, value: Optional[datetime]) -> Optional[str]:
        return utc_naive_to_aware_iso(value)


# --- Posts ---

class PostOut(BaseModel):
    id: int
    user_id: int
    environment_id: int
    feed_id: Optional[str] = None
    xsec_token: Optional[str] = None
    post_url: Optional[str] = None
    title: str
    content: str
    image_urls: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    ai_origin_type: str = "manual"
    account_name: Optional[str] = None
    status: str
    like_count: int
    comment_count: int
    collect_count: int
    share_count: int
    view_count: int
    published_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @field_serializer("published_at", "scheduled_at", "last_synced_at", "created_at")
    def serialize_datetimes(self, value: Optional[datetime]) -> Optional[str]:
        return utc_naive_to_aware_iso(value)

    model_config = {"from_attributes": True}


class PostListOut(BaseModel):
    items: list[PostOut]
    total: int
    page: int
    limit: int


class PostStatsOut(BaseModel):
    post_id: int
    feed_id: Optional[str]
    like_count: int
    comment_count: int
    collect_count: int
    share_count: int
    view_count: int
    status: str
    sync_reason: Optional[str] = None
    last_synced_at: Optional[datetime] = None

    @field_serializer("last_synced_at")
    def serialize_last_synced_at(self, value: Optional[datetime]) -> Optional[str]:
        return utc_naive_to_aware_iso(value)


class PostUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    scheduled_at: Optional[datetime] = None
    ai_origin_type: Optional[str] = None

    @field_validator("title")
    @classmethod
    def validate_update_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        title = value.strip()
        if not title:
            raise ValueError("标题不能为空")
        if len(title) > 20:
            raise ValueError("标题不能超过20字")
        return title

    @field_validator("content")
    @classmethod
    def validate_update_content(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        content = value.strip()
        if not content:
            raise ValueError("正文不能为空")
        if len(content) > 1000:
            raise ValueError("正文不能超过1000字")
        return content

    @field_validator("ai_origin_type")
    @classmethod
    def validate_update_ai_origin_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        allowed = {"manual", "text_ai", "image_ai", "all_ai"}
        normalized = value.strip()
        if normalized not in allowed:
            raise ValueError("AI 标记无效")
        return normalized


class AccountNoteOut(BaseModel):
    id: int
    environment_id: int
    account_name: str
    profile_nickname: Optional[str] = None
    red_id: Optional[str] = None
    feed_id: Optional[str] = None
    identity_status: str = "resolved"
    creator_identity_key: Optional[str] = None
    identity_match_method: Optional[str] = None
    identity_match_confidence: Optional[float] = None
    creator_published_at_raw: Optional[str] = None
    creator_first_seen_at: Optional[datetime] = None
    creator_last_seen_at: Optional[datetime] = None
    creator_synced_at: Optional[datetime] = None
    homepage_synced_at: Optional[datetime] = None
    source_post_id: Optional[int] = None
    xsec_token: Optional[str] = None
    post_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    title: str
    content: Optional[str] = None
    image_urls: Optional[list[str]] = None
    ai_origin_type: Optional[str] = None
    primary_content_tag: Optional[str] = None
    secondary_content_tag: Optional[str] = None
    status: str = "active"
    content_status: Optional[str] = None
    content_missing_reason: Optional[str] = None
    liked_count: int
    comment_count: int
    collected_count: int
    share_count: int
    view_count: int = 0
    exposure_count: int = 0
    cover_click_rate: float = 0.0
    is_promoted: bool = False
    promoted_first_seen_at: Optional[datetime] = None
    promoted_last_seen_at: Optional[datetime] = None
    promoted_source: Optional[str] = None
    published_at: Optional[datetime] = None
    detail_synced_at: Optional[datetime] = None
    sort_index: int
    assigned_runner_environment_id: Optional[int] = None
    assigned_runner_account_name: Optional[str] = None
    assignment_updated_at: Optional[datetime] = None
    owner_user_id: Optional[int] = None
    owner_username: Optional[str] = None
    owner_role: Optional[str] = None
    has_paid_report: bool = False
    has_creative_report: bool = False
    today_browse_count: int = 0
    first_synced_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_serializer(
        "promoted_first_seen_at",
        "promoted_last_seen_at",
        "creator_first_seen_at",
        "creator_last_seen_at",
        "creator_synced_at",
        "homepage_synced_at",
        "published_at",
        "detail_synced_at",
        "assignment_updated_at",
        "first_synced_at",
        "last_seen_at",
        "created_at",
        "updated_at",
    )
    def serialize_note_datetimes(self, value: Optional[datetime]) -> Optional[str]:
        return utc_naive_to_aware_iso(value)

    model_config = {"from_attributes": True}


class AccountNoteListOut(BaseModel):
    items: list[AccountNoteOut]
    total: int
    page: int
    limit: int
    total_accounts: int
    dashboard: Optional[dict[str, Any]] = None


class AccountNoteBrowseRecordRequest(BaseModel):
    browse_source: str = "link_click"

    @field_validator("browse_source")
    @classmethod
    def validate_browse_source(cls, value: str) -> str:
        normalized = (value or "").strip()
        allowed = {"link_click", "single_sync", "bulk_sync"}
        if normalized not in allowed:
            raise ValueError("浏览来源无效")
        return normalized


class AccountNoteSyncOut(BaseModel):
    synced_accounts: int
    created_notes: int
    updated_notes: int
    metric_synced_notes: int = 0
    total_notes: int
    message: Optional[str] = None


class AccountNoteUpdateRequest(BaseModel):
    ai_origin_type: Optional[str] = None

    @field_validator("ai_origin_type")
    @classmethod
    def validate_account_note_ai_origin_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        allowed = {"manual", "text_ai", "image_ai", "all_ai"}
        normalized = (value or "").strip()
        if normalized == "":
            raise ValueError("账号数据标记不能为空")
        if normalized not in allowed:
            raise ValueError("AI 标记无效")
        return normalized


class AccountNoteBatchUpdateRequest(BaseModel):
    note_ids: list[int] = Field(default_factory=list)
    ai_origin_type: str

    @field_validator("note_ids")
    @classmethod
    def validate_note_ids(cls, value: list[int]) -> list[int]:
        normalized = [int(item) for item in value if int(item) > 0]
        if not normalized:
            raise ValueError("请选择至少一条账号帖子")
        return normalized

    @field_validator("ai_origin_type")
    @classmethod
    def validate_batch_account_note_ai_origin_type(cls, value: str) -> str:
        allowed = {"manual", "text_ai", "image_ai", "all_ai"}
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("账号数据标记不能为空")
        if normalized not in allowed:
            raise ValueError("AI 标记无效")
        return normalized


class AccountNoteContentTagRequest(BaseModel):
    environment_id: Optional[int] = None
    keyword: Optional[str] = None
    ai_origin_type: Optional[str] = None
    status: Optional[str] = "all"
    concurrency: int = Field(default=20, ge=1, le=50)


class AccountNoteContentTagOut(BaseModel):
    matched_count: int
    tagged_count: int
    failed_count: int
    concurrency: int
    primary_counts: dict[str, int] = Field(default_factory=dict)
    failed_items: list[dict] = Field(default_factory=list)


class ReportListOut(BaseModel):
    report_type: str
    start_date: str
    end_date: str
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    total_accounts: int
    total_rows: int
    page: int
    limit: int
    items: list[dict] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)


class CreativeReportCompareOut(BaseModel):
    report_type: str
    start_date: str
    end_date: str
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    tags: list[dict] = Field(default_factory=list)
    granularities: dict[str, dict] = Field(default_factory=dict)
