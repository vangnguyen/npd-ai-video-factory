from pathlib import Path

import pytest

from app.artifacts import ArtifactAccessError, resolve_recorded_artifact
from app.models import Artifact, JobRecord, VideoJobCreate


def request_model() -> VideoJobCreate:
    return VideoJobCreate.model_validate({
        "topic": "video test",
        "project": "vinhomes-green-paradise",
        "video": {"duration_seconds": 45, "aspect": "9:16", "language": "vi", "template": "real-estate-short-v1"},
        "content": {"objective": "lead_generation", "audience": "khach hang", "tone": "tin cay", "cta": "Dang ky tham quan"},
        "media": {"source": "local", "project_asset_folder": "vinhomes-green-paradise", "minimum_clips": 5, "allow_stock": False, "allow_ai_generation": False},
    })


def test_only_recorded_artifacts_are_served(tmp_path: Path):
    record = JobRecord.new(job_id="vid_1234567890123_abcdef1234", request=request_model())
    job_dir = tmp_path / record.job_id
    job_dir.mkdir()
    final = job_dir / "final.mp4"
    final.write_bytes(b"video")
    record = record.model_copy(update={
        "artifacts": [Artifact(kind="video", name="final.mp4", url=f"/api/v1/video-jobs/{record.job_id}/artifacts/final.mp4")]
    })
    assert resolve_recorded_artifact(tmp_path, record, "final.mp4") == final.resolve()
    with pytest.raises(ArtifactAccessError):
        resolve_recorded_artifact(tmp_path, record, "secret.env")


def test_path_traversal_is_rejected(tmp_path: Path):
    record = JobRecord.new(job_id="vid_1234567890123_abcdef1234", request=request_model())
    record = record.model_copy(update={
        "artifacts": [Artifact(kind="metadata", name="safe.json", url="/safe.json")]
    })
    with pytest.raises(ArtifactAccessError):
        resolve_recorded_artifact(tmp_path, record, "../safe.json")
