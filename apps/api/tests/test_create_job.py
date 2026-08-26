from pathlib import Path
from types import SimpleNamespace

import pytest

from app.main import create_video_job
from app.models import JobRecord, VideoJobCreate


def sample_request() -> VideoJobCreate:
    root = Path(__file__).resolve().parents[3]
    return VideoJobCreate.model_validate_json(
        (root / "examples" / "vinhomes-green-paradise.request.json").read_text(encoding="utf-8")
    )


class FakeStore:
    def __init__(self, existing: JobRecord | None = None):
        self.existing = existing
        self.enqueued: list[str] = []

    async def create(self, candidate: JobRecord, *, idempotency_key: str | None = None) -> JobRecord:
        assert idempotency_key == "same-request"
        return self.existing or candidate

    async def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


def fake_request(store: FakeStore):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(job_store=store)))


@pytest.mark.asyncio
async def test_new_job_is_enqueued_once() -> None:
    store = FakeStore()
    response = await create_video_job(sample_request(), fake_request(store), "same-request")
    assert store.enqueued == [response.job_id]


@pytest.mark.asyncio
async def test_idempotency_hit_is_not_enqueued_again() -> None:
    existing = JobRecord.new(job_id="vid_existing_1234", request=sample_request())
    store = FakeStore(existing)
    response = await create_video_job(sample_request(), fake_request(store), "same-request")
    assert response.job_id == existing.job_id
    assert store.enqueued == []
