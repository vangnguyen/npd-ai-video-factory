from __future__ import annotations

from pathlib import Path

from .models import JobRecord


class ArtifactAccessError(ValueError):
    pass


def job_directory(root: Path, job_id: str) -> Path:
    if not job_id.startswith("vid_") or len(job_id) > 80:
        raise ArtifactAccessError("invalid job id")
    root_resolved = root.resolve()
    candidate = (root_resolved / job_id).resolve()
    if candidate.parent != root_resolved:
        raise ArtifactAccessError("job directory escaped storage root")
    return candidate


def resolve_recorded_artifact(root: Path, record: JobRecord, artifact_name: str) -> Path:
    allowed = {artifact.name for artifact in record.artifacts}
    if artifact_name not in allowed:
        raise ArtifactAccessError("artifact not recorded for job")
    if Path(artifact_name).name != artifact_name:
        raise ArtifactAccessError("invalid artifact name")
    candidate = (job_directory(root, record.job_id) / artifact_name).resolve()
    expected_parent = job_directory(root, record.job_id)
    if candidate.parent != expected_parent:
        raise ArtifactAccessError("artifact escaped job directory")
    if not candidate.is_file():
        raise ArtifactAccessError("artifact file missing")
    return candidate
