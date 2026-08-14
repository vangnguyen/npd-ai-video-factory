from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VideoConfig(StrictModel):
    duration_seconds: int = Field(ge=15, le=90)
    aspect: Literal["9:16"] = "9:16"
    language: Literal["vi"] = "vi"
    template: Literal["real-estate-short-v1"] = "real-estate-short-v1"


class ContentConfig(StrictModel):
    objective: Literal["lead_generation", "awareness", "education"] = "lead_generation"
    audience: str = Field(min_length=1, max_length=300)
    tone: str = Field(min_length=1, max_length=300)
    cta: str = Field(min_length=1, max_length=300)


class MediaConfig(StrictModel):
    source: Literal["local"] = "local"
    project_asset_folder: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,80}$")
    minimum_clips: int = Field(default=5, ge=1, le=20)
    allow_stock: Literal[False] = False
    allow_ai_generation: Literal[False] = False


class VideoJobCreate(StrictModel):
    topic: str = Field(min_length=3, max_length=500)
    project: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,80}$")
    video: VideoConfig
    content: ContentConfig
    media: MediaConfig


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    FAILED = "failed"


class JobStage(StrEnum):
    QUEUED = "queued"
    SCRIPTING = "scripting"
    STORYBOARDING = "storyboarding"
    GENERATING_VOICE = "generating_voice"
    GENERATING_SUBTITLES = "generating_subtitles"
    RESOLVING_ASSETS = "resolving_assets"
    BUILDING_MANIFEST = "building_manifest"
    RENDERING = "rendering"
    QUALITY_CHECK = "quality_check"
    AWAITING_REVIEW = "awaiting_review"
    FAILED = "failed"


STAGE_ORDER: dict[JobStage, int] = {
    JobStage.QUEUED: 0,
    JobStage.SCRIPTING: 10,
    JobStage.STORYBOARDING: 20,
    JobStage.GENERATING_VOICE: 30,
    JobStage.GENERATING_SUBTITLES: 40,
    JobStage.RESOLVING_ASSETS: 50,
    JobStage.BUILDING_MANIFEST: 60,
    JobStage.RENDERING: 70,
    JobStage.QUALITY_CHECK: 90,
    JobStage.AWAITING_REVIEW: 100,
    JobStage.FAILED: 1000,
}


class Artifact(StrictModel):
    kind: Literal["script", "storyboard", "audio", "subtitle", "manifest", "video", "metadata"]
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    url: str


class JobError(StrictModel):
    code: str
    message: str
    failed_stage: JobStage
    retryable: bool = False
    details: list[dict] = Field(default_factory=list)


class JobRecord(StrictModel):
    job_id: str
    status: JobStatus
    stage: JobStage
    progress: int = Field(ge=0, le=100)
    request: VideoJobCreate
    artifacts: list[Artifact] = Field(default_factory=list)
    error: JobError | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(cls, *, job_id: str, request: VideoJobCreate) -> "JobRecord":
        now = datetime.now(timezone.utc)
        return cls(
            job_id=job_id,
            status=JobStatus.QUEUED,
            stage=JobStage.QUEUED,
            progress=0,
            request=request,
            created_at=now,
            updated_at=now,
        )


class JobCreateResponse(StrictModel):
    job_id: str
    status: JobStatus
    stage: JobStage
    progress: int
    status_url: str


class ErrorBody(StrictModel):
    code: str
    message: str
    failed_stage: JobStage | None = None
    retryable: bool = False
    details: list[dict] = Field(default_factory=list)


class ErrorEnvelope(StrictModel):
    error: ErrorBody
