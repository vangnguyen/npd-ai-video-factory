from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import JobRecord, JobStage, JobStatus, VideoJobCreate
from app.state import validate_transition


VALID_REQUEST = {
    "topic": "3 ly do nen chu y Vinhomes Green Paradise tuan nay",
    "project": "vinhomes-green-paradise",
    "video": {
        "duration_seconds": 45,
        "aspect": "9:16",
        "language": "vi",
        "template": "real-estate-short-v1",
    },
    "content": {
        "objective": "lead_generation",
        "audience": "khach hang quan tam bat dong san Can Gio",
        "tone": "thong tin, tin cay, khong phong dai",
        "cta": "Dang ky tham quan sa ban",
    },
    "media": {
        "source": "local",
        "project_asset_folder": "vinhomes-green-paradise",
        "minimum_clips": 5,
        "allow_stock": False,
        "allow_ai_generation": False,
    },
}


def test_request_contract_accepts_sprint_1_fixture():
    model = VideoJobCreate.model_validate(VALID_REQUEST)
    assert model.video.duration_seconds == 45
    assert model.media.source == "local"


def test_request_contract_forbids_unknown_fields():
    invalid = {**VALID_REQUEST, "unexpected": True}
    with pytest.raises(ValidationError):
        VideoJobCreate.model_validate(invalid)


def test_request_contract_rejects_ai_generation():
    invalid = {**VALID_REQUEST, "media": {**VALID_REQUEST["media"], "allow_ai_generation": True}}
    with pytest.raises(ValidationError):
        VideoJobCreate.model_validate(invalid)


def test_transition_cannot_move_progress_backwards():
    request = VideoJobCreate.model_validate(VALID_REQUEST)
    now = datetime.now(timezone.utc)
    current = JobRecord(
        job_id="vid_test",
        status=JobStatus.RUNNING,
        stage=JobStage.STORYBOARDING,
        progress=20,
        request=request,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ValueError, match="progress cannot decrease"):
        validate_transition(current, stage=JobStage.SCRIPTING, progress=10)


def test_transition_can_advance():
    request = VideoJobCreate.model_validate(VALID_REQUEST)
    record = JobRecord.new(job_id="vid_test", request=request)
    validate_transition(record, stage=JobStage.SCRIPTING, progress=10)
