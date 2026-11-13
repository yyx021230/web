"""Explicit review scopes for account master and historical identity changes."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

PositiveId = Annotated[int, Field(strict=True, gt=0)]


class ApplyMasterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_hash: str = Field(
        pattern=r"^[a-f0-9]{64}$", description="SHA256 of the previewed CSV"
    )
    rows: list[PositiveId] = Field(
        min_length=1, max_length=2000, description="Explicit spreadsheet row numbers"
    )
    include_history: bool = Field(
        default=False,
        description="Attribute previewed historical notes without deleting originals",
    )
    replace_all: bool = Field(
        default=False,
        description="Confirm the entire reviewed sheet as the sole current account roster",
    )


class HistoryReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: PositiveId = Field(description="Independent account identity")
    environment_id: PositiveId = Field(
        description="Historical source only; never a future account binding"
    )
    note_ids: list[PositiveId] = Field(
        min_length=1, max_length=500, description="Reviewed historical note IDs"
    )
    expected_revision: PositiveId = Field(
        description="Account revision observed by reviewer"
    )
    confirm_identity: Literal[True] = Field(
        description="Explicit historical identity confirmation"
    )


class CloudImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_ids: list[PositiveId] = Field(
        min_length=1,
        max_length=100,
        description="Active independent accounts to import",
    )


class ProfileLocatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_url: str = Field(min_length=1, max_length=1000)
    expected_revision: PositiveId


class MasterSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["posts", "engagement", "details"]
    account_ids: list[PositiveId] | None = Field(default=None, max_length=2000)
    runner_ids: list[PositiveId] = Field(default_factory=list, max_length=20)
    runner_assignments: dict[str, list[PositiveId]] | None = None
    target_note_ids: list[PositiveId] | None = Field(default=None, max_length=1000)
    concurrency: int = Field(default=5, ge=1, le=5)
    homepage_sync_mode: Literal["supplement_only", "create_missing"] = "supplement_only"
    limit_per_account: int = Field(default=120, ge=1, le=1000)
    sync_mode: Literal["all", "unpublished_only"] = "all"
    sync_limit: int | None = Field(default=None, ge=1, le=1000)
    sync_limit_per_runner: int | None = Field(default=None, ge=1, le=60)
    pause_seconds_min: float | None = Field(default=None, ge=0, le=900)
    pause_seconds_max: float | None = Field(default=None, ge=0, le=900)
    max_post_age_days: int | None = Field(default=None, ge=0, le=3650)


class MasterHomepageWorkerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: PositiveId
    expected_revision: PositiveId
    runner_id: PositiveId
    limit: int = Field(default=120, ge=1, le=1000)
    homepage_sync_mode: Literal["supplement_only", "create_missing"] = "supplement_only"


class MasterDetailWorkerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: PositiveId
    expected_revision: PositiveId
    runner_id: PositiveId
    note_ids: list[PositiveId] = Field(min_length=1, max_length=1000)
    sync_limit_per_runner: int | None = Field(default=None, ge=1, le=60)
    pause_seconds_min: float | None = Field(default=None, ge=0, le=900)
    pause_seconds_max: float | None = Field(default=None, ge=0, le=900)
