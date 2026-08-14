from pathlib import Path

import pytest

from app.providers import StoryboardResult, StoryboardScene
from npd_worker.pipeline import (
    VideoQCError,
    WorkerConfig,
    build_subtitles,
    ensure_brand_logo,
    safe_job_dir,
    validate_probe_payload,
)


def test_safe_job_dir_stays_under_root(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    root.mkdir()
    result = safe_job_dir(root, "vid_12345678")
    assert result.parent == root.resolve()


@pytest.mark.parametrize("job_id", ["../escape", "vid_../../escape", "other_1234", "vid_a/b"])
def test_safe_job_dir_rejects_invalid_ids(tmp_path: Path, job_id: str) -> None:
    with pytest.raises(ValueError):
        safe_job_dir(tmp_path, job_id)


def test_build_subtitles_tracks_storyboard_timeline() -> None:
    storyboard = StoryboardResult(
        scenes=[
            StoryboardScene(
                id="scene_01",
                order=1,
                start_seconds=0,
                duration_seconds=3.5,
                role="hook",
                narration="Mở đầu",
                on_screen_text="Mở đầu",
                visual_query="project hook",
            ),
            StoryboardScene(
                id="scene_02",
                order=2,
                start_seconds=3.5,
                duration_seconds=4.0,
                role="information",
                narration="Thông tin chính",
                on_screen_text=None,
                visual_query="project information",
            ),
        ]
    )
    subtitles = build_subtitles(storyboard)
    assert subtitles == [
        {"start_seconds": 0.0, "end_seconds": 3.5, "text": "Mở đầu"},
        {"start_seconds": 3.5, "end_seconds": 7.5, "text": "Thông tin chính"},
    ]


def test_validate_probe_payload_accepts_target_video() -> None:
    payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "45.02"},
    }
    result = validate_probe_payload(payload, expected_duration=45, require_audio=True)
    assert result["video_codec"] == "h264"
    assert result["audio_codec"] == "aac"
    assert result["width"] == 1080
    assert result["height"] == 1920


def test_validate_probe_payload_rejects_missing_audio() -> None:
    payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920}
        ],
        "format": {"duration": "45"},
    }
    with pytest.raises(VideoQCError, match="audio"):
        validate_probe_payload(payload, expected_duration=45, require_audio=True)


def test_logo_placeholder_is_created_inside_job_dir(tmp_path: Path) -> None:
    config = WorkerConfig(
        job_root=tmp_path / "jobs",
        asset_root=tmp_path / "assets",
        schema_path=tmp_path / "schema.json",
        renderer_url="http://renderer:3001",
        brand_name="Ngọc Phương Đông",
        logo_path=tmp_path / "missing-logo.png",
        tts_provider="espeak",
        espeak_voice="vi",
        espeak_rate=145,
        renderer_timeout_seconds=600,
    )
    job_dir = tmp_path / "jobs" / "vid_12345678"
    job_dir.mkdir(parents=True)
    logo = ensure_brand_logo(config, job_dir)
    assert logo.parent == job_dir
    assert "Ngọc Phương Đông" in logo.read_text(encoding="utf-8")
