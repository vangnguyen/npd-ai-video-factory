from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from redis.asyncio import Redis

from .artifacts import ArtifactAccessError, resolve_recorded_artifact
from .config import settings
from .legacy_telemetry import LegacyTelemetry
from .models import JobCreateResponse, JobRecord, VideoJobCreate
from .state import RedisJobStore


def new_job_id() -> str:
    millis = int(time.time() * 1000)
    return f"vid_{millis:013d}_{uuid.uuid4().hex[:10]}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.job_storage_root.mkdir(parents=True, exist_ok=True)
    settings.asset_storage_root.mkdir(parents=True, exist_ok=True)
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    app.state.redis = redis
    app.state.job_store = RedisJobStore(redis)
    app.state.legacy_telemetry = LegacyTelemetry.from_environment()
    try:
        yield
    finally:
        await redis.aclose()


app = FastAPI(title="NPD AI Video Factory API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def record_legacy_route_access(request: Request, call_next):
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_template = getattr(route, "path", None)
        telemetry = getattr(request.app.state, "legacy_telemetry", None)
        if telemetry is not None:
            telemetry.record(
                route=route_template,
                method=request.method,
                status_code=status_code,
                peer_host=request.client.host if request.client else None,
                claimed_caller_id=request.headers.get("X-NPD-Caller-ID"),
                user_agent=request.headers.get("User-Agent"),
            )


def store_from(request: Request) -> RedisJobStore:
    return request.app.state.job_store


def not_found(message: str = "Job not found.") -> HTTPException:
    return HTTPException(status_code=404, detail={"error": {"code": "ARTIFACT_NOT_FOUND", "message": message}})


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    try:
        await request.app.state.redis.ping()
        storage = settings.job_storage_root.resolve()
        storage.mkdir(parents=True, exist_ok=True)
        probe = storage / ".readyz"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "INTERNAL_ERROR", "message": "Readiness dependency unavailable."}},
        ) from exc
    return {"status": "ready"}


@app.post("/api/v1/video-jobs", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_video_job(
    payload: VideoJobCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
) -> JobCreateResponse:
    store = store_from(request)
    record = JobRecord.new(job_id=new_job_id(), request=payload)
    record = await store.create(record, idempotency_key=idempotency_key)
    if record.stage.value == "queued":
        await store.enqueue(record.job_id)
    return JobCreateResponse(
        job_id=record.job_id,
        status=record.status,
        stage=record.stage,
        progress=record.progress,
        status_url=f"/api/v1/video-jobs/{record.job_id}",
    )


@app.get("/api/v1/video-jobs/{job_id}", response_model=JobRecord)
async def get_video_job(job_id: str, request: Request) -> JobRecord:
    if not job_id.startswith("vid_") or len(job_id) > 80:
        raise not_found()
    record = await store_from(request).get(job_id)
    if record is None:
        raise not_found()
    return record


@app.get("/api/v1/video-jobs/{job_id}/artifacts/{artifact_name}")
async def get_video_artifact(job_id: str, artifact_name: str, request: Request) -> FileResponse:
    record = await store_from(request).get(job_id)
    if record is None:
        raise not_found()
    try:
        path = resolve_recorded_artifact(settings.job_storage_root, record, artifact_name)
    except ArtifactAccessError as exc:
        raise not_found("Artifact not found.") from exc
    return FileResponse(path=path, filename=artifact_name)
