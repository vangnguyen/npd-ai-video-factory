from __future__ import annotations

from datetime import datetime, timezone

from redis.asyncio import Redis
from redis.exceptions import WatchError

from .models import Artifact, JobError, JobRecord, JobStage, JobStatus, STAGE_ORDER


QUEUE_KEY = "npd:video-jobs:queue"


def validate_transition(current: JobRecord, *, stage: JobStage, progress: int) -> None:
    if progress < current.progress:
        raise ValueError("job progress cannot decrease")
    if stage != JobStage.FAILED and STAGE_ORDER[stage] < STAGE_ORDER[current.stage]:
        raise ValueError("job stage cannot move backwards")


class RedisJobStore:
    def __init__(self, redis: Redis):
        self.redis = redis

    @staticmethod
    def job_key(job_id: str) -> str:
        return f"npd:video-job:{job_id}"

    @staticmethod
    def idempotency_key(key: str) -> str:
        return f"npd:video-idempotency:{key}"

    async def create(self, record: JobRecord, *, idempotency_key: str | None = None) -> JobRecord:
        if idempotency_key:
            existing_job_id = await self.redis.get(self.idempotency_key(idempotency_key))
            if existing_job_id:
                if isinstance(existing_job_id, bytes):
                    existing_job_id = existing_job_id.decode()
                existing = await self.get(existing_job_id)
                if existing:
                    return existing

        created = await self.redis.set(self.job_key(record.job_id), record.model_dump_json(), nx=True)
        if not created:
            existing = await self.get(record.job_id)
            if existing:
                return existing
            raise RuntimeError("job key collision")

        if idempotency_key:
            await self.redis.set(self.idempotency_key(idempotency_key), record.job_id, ex=86400, nx=True)
        return record

    async def enqueue(self, job_id: str) -> None:
        await self.redis.rpush(QUEUE_KEY, job_id)

    async def get(self, job_id: str) -> JobRecord | None:
        raw = await self.redis.get(self.job_key(job_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return JobRecord.model_validate_json(raw)

    async def _mutate(self, job_id: str, mutate) -> JobRecord:
        key = self.job_key(job_id)
        while True:
            try:
                async with self.redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(key)
                    raw = await pipe.get(key)
                    if raw is None:
                        raise KeyError(job_id)
                    if isinstance(raw, bytes):
                        raw = raw.decode()
                    current = JobRecord.model_validate_json(raw)
                    updated = mutate(current)
                    pipe.multi()
                    pipe.set(key, updated.model_dump_json())
                    await pipe.execute()
                    return updated
            except WatchError:
                continue

    async def update_stage(self, job_id: str, *, status: JobStatus, stage: JobStage, progress: int) -> JobRecord:
        def mutate(current: JobRecord) -> JobRecord:
            validate_transition(current, stage=stage, progress=progress)
            return current.model_copy(update={
                "status": status,
                "stage": stage,
                "progress": progress,
                "updated_at": datetime.now(timezone.utc),
            })
        return await self._mutate(job_id, mutate)

    async def add_artifact(self, job_id: str, *, artifact: Artifact) -> JobRecord:
        def mutate(current: JobRecord) -> JobRecord:
            artifacts = [item for item in current.artifacts if item.name != artifact.name]
            artifacts.append(artifact)
            return current.model_copy(update={"artifacts": artifacts, "updated_at": datetime.now(timezone.utc)})
        return await self._mutate(job_id, mutate)

    async def fail(self, job_id: str, *, error: JobError) -> JobRecord:
        def mutate(current: JobRecord) -> JobRecord:
            return current.model_copy(update={
                "status": JobStatus.FAILED,
                "stage": JobStage.FAILED,
                "error": error,
                "updated_at": datetime.now(timezone.utc),
            })
        return await self._mutate(job_id, mutate)
