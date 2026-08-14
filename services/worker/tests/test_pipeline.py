import asyncio
import wave
from pathlib import Path
from typing import Any

import pytest
import httpx

from app.assets import AssetResolutionError
from app.models import Artifact, JobError, JobRecord, JobStage, JobStatus, VideoJobCreate
from app.providers import StoryboardResult, StoryboardScene, VoiceResult
from npd_worker.pipeline import (
    ManifestValidationError,
    NarrationCue,
    NarrationTiming,
    RendererFailed,
    VideoQCError,
    WorkerConfig,
    build_subtitles,
    call_renderer,
    ensure_brand_logo,
    get_tts_provider,
    parse_volume_output,
    safe_job_dir,
    synthesize_storyboard_voice,
    synthesize_timed_narration,
    validate_narration_audio,
    validate_wav,
    validate_probe_payload,
    validate_visual_luma_values,
    run_job,
)
from npd_worker.preflight import validate_pilot_assets


def _config(tmp_path: Path, **overrides) -> WorkerConfig:
    values = dict(
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
    values.update(overrides)
    return WorkerConfig(**values)


class MemoryStore:
    def __init__(self, record: JobRecord):
        self.record = record

    async def get(self, job_id: str) -> JobRecord | None:
        return self.record if self.record.job_id == job_id else None

    async def update_stage(self, job_id: str, *, status: JobStatus, stage: JobStage, progress: int) -> JobRecord:
        assert job_id == self.record.job_id
        assert progress >= self.record.progress
        self.record = self.record.model_copy(update={"status": status, "stage": stage, "progress": progress})
        return self.record

    async def add_artifact(self, job_id: str, *, artifact: Artifact) -> JobRecord:
        assert job_id == self.record.job_id
        artifacts = [item for item in self.record.artifacts if item.name != artifact.name]
        self.record = self.record.model_copy(update={"artifacts": [*artifacts, artifact]})
        return self.record

    async def fail(self, job_id: str, *, error: JobError) -> JobRecord:
        assert job_id == self.record.job_id
        self.record = self.record.model_copy(
            update={"status": JobStatus.FAILED, "stage": JobStage.FAILED, "error": error}
        )
        return self.record


class FixtureTTS:
    async def synthesize(self, *, text: str, language: str, output_path: Path) -> VoiceResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8_000)
            wav.writeframes(b"\xe8\x03" * 8_000)
        return VoiceResult(path=output_path, duration_seconds=1, provider="fixture", voice="vi")


def pipeline_fixture(tmp_path: Path) -> tuple[MemoryStore, WorkerConfig]:
    root = Path(__file__).resolve().parents[3]
    request = VideoJobCreate.model_validate_json(
        (root / "examples" / "vinhomes-green-paradise.request.json").read_text(encoding="utf-8")
    )
    record = JobRecord.new(job_id="vid_12345678", request=request)
    asset_folder = tmp_path / "assets" / request.media.project_asset_folder
    asset_folder.mkdir(parents=True)
    for index in range(5):
        (asset_folder / f"fixture-{index}.png").write_bytes(b"png")
    config = WorkerConfig(
        job_root=tmp_path / "jobs",
        asset_root=tmp_path / "assets",
        schema_path=root / "packages" / "contracts" / "video-manifest.schema.json",
        renderer_url="http://renderer:3001",
        brand_name="Ngoc Phuong Dong",
        logo_path=tmp_path / "missing-logo.png",
        tts_provider="fixture",
        espeak_voice="vi",
        espeak_rate=145,
        renderer_timeout_seconds=30,
    )
    return MemoryStore(record), config


def qc_result() -> dict[str, Any]:
    return {
        "duration_seconds": 45.0,
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "video_codec": "h264",
        "audio_codec": "aac",
        "size_bytes": 100_001,
    }


def test_safe_job_dir_stays_under_root(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    root.mkdir()
    result = safe_job_dir(root, "vid_12345678")
    assert result.parent == root.resolve()


@pytest.mark.parametrize("job_id", ["../escape", "vid_../../escape", "other_1234", "vid_a/b"])
def test_safe_job_dir_rejects_invalid_ids(tmp_path: Path, job_id: str) -> None:
    with pytest.raises(ValueError):
        safe_job_dir(tmp_path, job_id)


def test_build_subtitles_tracks_measured_narration_timing() -> None:
    timing = NarrationTiming(
        duration_seconds=7.5,
        cues=[
            NarrationCue(scene_id="scene_01", start_seconds=0.15, end_seconds=1.15, text="Mở đầu"),
            NarrationCue(
                scene_id="scene_02",
                start_seconds=3.65,
                end_seconds=4.65,
                text="Thông tin chính",
            ),
        ],
    )
    subtitles = build_subtitles(timing)
    assert subtitles == [
        {"start_seconds": 0.15, "end_seconds": 1.15, "text": "Mở đầu"},
        {"start_seconds": 3.65, "end_seconds": 4.65, "text": "Thông tin chính"},
    ]


@pytest.mark.asyncio
async def test_timed_narration_master_aligns_audio_and_subtitle_cues(tmp_path: Path) -> None:
    storyboard = StoryboardResult(
        scenes=[
            StoryboardScene(
                id="scene_01",
                order=1,
                start_seconds=0,
                duration_seconds=2,
                role="hook",
                narration="Mở đầu rõ ràng",
                on_screen_text=None,
                visual_query="hook",
            ),
            StoryboardScene(
                id="scene_02",
                order=2,
                start_seconds=2,
                duration_seconds=2,
                role="information",
                narration="Thông tin chính",
                on_screen_text=None,
                visual_query="information",
            ),
        ]
    )
    output = tmp_path / "narration.wav"
    timing_path = tmp_path / "narration-timing.json"
    timing = await synthesize_timed_narration(
        FixtureTTS(),
        storyboard=storyboard,
        language="vi",
        output_path=output,
        timing_path=timing_path,
        duration_seconds=4,
    )

    assert validate_narration_audio(output, timing, expected_duration=4) == pytest.approx(4)
    assert [(cue.scene_id, cue.start_seconds, cue.end_seconds) for cue in timing.cues] == [
        ("scene_01", 0.15, 1.15),
        ("scene_02", 2.15, 3.15),
    ]
    assert NarrationTiming.model_validate_json(timing_path.read_text(encoding="utf-8")) == timing


def test_visual_and_audio_qc_reject_black_or_silent_outputs() -> None:
    assert validate_visual_luma_values([35.0, 42.0])["dark_visual_sample_ratio"] == 0
    with pytest.raises(VideoQCError, match="black"):
        validate_visual_luma_values([0.0, 0.0, 20.0])
    assert parse_volume_output("mean_volume: -24.8 dB\nmax_volume: -3.0 dB")["audio_peak_db"] == -3
    with pytest.raises(VideoQCError, match="silent"):
        parse_volume_output("mean_volume: -70.0 dB\nmax_volume: -55.0 dB")


def test_validate_probe_payload_accepts_target_video() -> None:
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "30/1",
            },
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
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "30/1",
            }
        ],
        "format": {"duration": "45"},
    }
    with pytest.raises(VideoQCError, match="audio"):
        validate_probe_payload(payload, expected_duration=45, require_audio=True)


class _FakeTTSProvider:
    def __init__(self, duration_seconds: float = 0.5) -> None:
        self.calls: list[str] = []
        self.duration_seconds = duration_seconds

    async def synthesize(self, *, text: str, language: str, output_path: Path) -> None:
        assert language == "vi"
        self.calls.append(text)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8_000)
            wav.writeframes(b"\x01\x00" * round(self.duration_seconds * 8_000))


@pytest.mark.asyncio
async def test_storyboard_voice_is_aligned_and_padded_to_timeline(tmp_path: Path) -> None:
    storyboard = StoryboardResult(
        scenes=[
            StoryboardScene(
                id="scene_01",
                order=1,
                start_seconds=0,
                duration_seconds=2,
                role="hook",
                narration="Mở đầu",
                visual_query="project hook",
            ),
            StoryboardScene(
                id="scene_02",
                order=2,
                start_seconds=2,
                duration_seconds=2,
                role="cta",
                narration="Mở đầu",
                visual_query="project cta",
            ),
        ]
    )
    provider = _FakeTTSProvider()
    output = tmp_path / "narration.wav"

    duration = await synthesize_storyboard_voice(
        provider,
        storyboard=storyboard,
        language="vi",
        output_path=output,
    )

    assert duration == pytest.approx(4.0)
    assert validate_wav(output, expected_duration=4.0) == pytest.approx(4.0)
    assert provider.calls == ["Mở đầu"]
    assert not (tmp_path / "voice-scenes").exists()


@pytest.mark.asyncio
async def test_storyboard_voice_rejects_excessive_speedup(tmp_path: Path) -> None:
    storyboard = StoryboardResult(
        scenes=[
            StoryboardScene(
                id="scene_01",
                order=1,
                start_seconds=0,
                duration_seconds=2,
                role="hook",
                narration="Nội dung quá dài",
                visual_query="project hook",
            )
        ]
    )

    with pytest.raises(ValueError, match="production limit"):
        await synthesize_storyboard_voice(
            _FakeTTSProvider(duration_seconds=3),
            storyboard=storyboard,
            language="vi",
            output_path=tmp_path / "narration.wav",
        )

    assert not (tmp_path / "voice-scenes").exists()


def test_logo_placeholder_is_created_inside_job_dir(tmp_path: Path) -> None:
    config = _config(tmp_path)
    job_dir = tmp_path / "jobs" / "vid_12345678"
    job_dir.mkdir(parents=True)
    logo = ensure_brand_logo(config, job_dir)
    assert logo.parent == job_dir
    assert "Ngọc Phương Đông" in logo.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_pipeline_completes_and_registers_stage_artifacts(tmp_path: Path, monkeypatch) -> None:
    store, config = pipeline_fixture(tmp_path)

    async def fake_render(_config, *, output_path: Path, **_kwargs):
        output_path.write_bytes(b"0" * 100_001)
        return {"status": "success", "output_path": str(output_path)}

    async def fake_probe(*_args, **_kwargs):
        return qc_result()

    monkeypatch.setattr("npd_worker.pipeline.get_tts_provider", lambda _config: FixtureTTS())
    monkeypatch.setattr("npd_worker.pipeline.call_renderer", fake_render)
    monkeypatch.setattr("npd_worker.pipeline.probe_video", fake_probe)

    result = await run_job(store, store.record.job_id, config=config)

    assert result is not None
    assert result.status == JobStatus.AWAITING_REVIEW
    assert result.stage == JobStage.AWAITING_REVIEW
    assert result.progress == 100
    assert {artifact.name for artifact in result.artifacts} >= {
        "request.json",
        "script.json",
        "storyboard.json",
        "narration.wav",
        "narration-timing.json",
        "subtitles.srt",
        "resolved-assets.json",
        "video-manifest.json",
        "final.mp4",
        "qc.json",
    }


@pytest.mark.asyncio
async def test_pipeline_resumes_after_interruption_without_repeating_content_or_tts(
    tmp_path: Path, monkeypatch
) -> None:
    store, config = pipeline_fixture(tmp_path)

    async def interrupted_render(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr("npd_worker.pipeline.get_tts_provider", lambda _config: FixtureTTS())
    monkeypatch.setattr("npd_worker.pipeline.call_renderer", interrupted_render)
    with pytest.raises(asyncio.CancelledError):
        await run_job(store, store.record.job_id, config=config)

    assert store.record.stage == JobStage.RENDERING
    assert store.record.progress == 70

    class ExplodingContentProvider:
        async def generate_script(self, _request):
            raise AssertionError("script stage should have resumed from artifact")

        async def generate_storyboard(self, _request, _script):
            raise AssertionError("storyboard stage should have resumed from artifact")

    class ExplodingTTS:
        async def synthesize(self, **_kwargs):
            raise AssertionError("TTS stage should have resumed from artifact")

    async def resumed_render(_config, *, output_path: Path, **_kwargs):
        output_path.write_bytes(b"0" * 100_001)
        return {"status": "success", "output_path": str(output_path)}

    async def fake_probe(*_args, **_kwargs):
        return qc_result()

    monkeypatch.setattr("npd_worker.pipeline.DeterministicContentProvider", ExplodingContentProvider)
    monkeypatch.setattr("npd_worker.pipeline.get_tts_provider", lambda _config: ExplodingTTS())
    monkeypatch.setattr("npd_worker.pipeline.call_renderer", resumed_render)
    monkeypatch.setattr("npd_worker.pipeline.probe_video", fake_probe)

    result = await run_job(store, store.record.job_id, config=config)
    assert result is not None
    assert result.status == JobStatus.AWAITING_REVIEW


@pytest.mark.asyncio
async def test_asset_resolution_error_uses_stable_code_and_safe_message(tmp_path: Path, monkeypatch) -> None:
    store, config = pipeline_fixture(tmp_path)
    for asset in config.asset_root.rglob("*.png"):
        asset.unlink()
    monkeypatch.setattr("npd_worker.pipeline.get_tts_provider", lambda _config: FixtureTTS())

    result = await run_job(store, store.record.job_id, config=config)

    assert result is not None and result.error is not None
    assert result.error.code == "ASSET_RESOLUTION_FAILED"
    assert "expected at least" not in result.error.message


@pytest.mark.asyncio
async def test_renderer_and_qc_failures_use_stable_codes(tmp_path: Path, monkeypatch) -> None:
    store, config = pipeline_fixture(tmp_path)
    monkeypatch.setattr("npd_worker.pipeline.get_tts_provider", lambda _config: FixtureTTS())

    async def failed_render(*_args, **_kwargs):
        raise RendererFailed("internal renderer detail")

    monkeypatch.setattr("npd_worker.pipeline.call_renderer", failed_render)
    render_result = await run_job(store, store.record.job_id, config=config)
    assert render_result is not None and render_result.error is not None
    assert render_result.error.code == "RENDER_FAILED"
    assert "internal renderer detail" not in render_result.error.message

    store, config = pipeline_fixture(tmp_path / "qc-case")

    async def completed_render(_config, *, output_path: Path, **_kwargs):
        output_path.write_bytes(b"0" * 100_001)
        return {"status": "success", "output_path": str(output_path)}

    async def failed_probe(*_args, **_kwargs):
        raise VideoQCError("internal ffprobe detail")

    monkeypatch.setattr("npd_worker.pipeline.call_renderer", completed_render)
    monkeypatch.setattr("npd_worker.pipeline.probe_video", failed_probe)
    qc_failure = await run_job(store, store.record.job_id, config=config)
    assert qc_failure is not None and qc_failure.error is not None
    assert qc_failure.error.code == "QC_FAILED"
    assert "internal ffprobe detail" not in qc_failure.error.message


@pytest.mark.asyncio
async def test_content_tts_and_manifest_failures_use_stable_codes(tmp_path: Path, monkeypatch) -> None:
    class FailedContentProvider:
        async def generate_script(self, _request):
            raise RuntimeError("provider secret")

    store, config = pipeline_fixture(tmp_path / "content-case")
    monkeypatch.setattr("npd_worker.pipeline.DeterministicContentProvider", FailedContentProvider)
    monkeypatch.setattr("npd_worker.pipeline.get_tts_provider", lambda _config: FixtureTTS())
    content_failure = await run_job(store, store.record.job_id, config=config)
    assert content_failure is not None and content_failure.error is not None
    assert content_failure.error.code == "CONTENT_PROVIDER_FAILED"
    assert "provider secret" not in content_failure.error.message

    class FailedTTS:
        async def synthesize(self, **_kwargs):
            raise RuntimeError("tts secret")

    from app.providers import DeterministicContentProvider

    store, config = pipeline_fixture(tmp_path / "tts-case")
    monkeypatch.setattr("npd_worker.pipeline.DeterministicContentProvider", DeterministicContentProvider)
    monkeypatch.setattr("npd_worker.pipeline.get_tts_provider", lambda _config: FailedTTS())
    tts_failure = await run_job(store, store.record.job_id, config=config)
    assert tts_failure is not None and tts_failure.error is not None
    assert tts_failure.error.code == "TTS_PROVIDER_FAILED"
    assert "tts secret" not in tts_failure.error.message

    store, config = pipeline_fixture(tmp_path / "manifest-case")
    monkeypatch.setattr("npd_worker.pipeline.get_tts_provider", lambda _config: FixtureTTS())

    def failed_manifest(*_args, **_kwargs):
        raise ManifestValidationError("schema secret")

    monkeypatch.setattr("npd_worker.pipeline.persist_manifest", failed_manifest)
    manifest_failure = await run_job(store, store.record.job_id, config=config)
    assert manifest_failure is not None and manifest_failure.error is not None
    assert manifest_failure.error.code == "MANIFEST_VALIDATION_FAILED"
    assert "schema secret" not in manifest_failure.error.message


@pytest.mark.asyncio
async def test_renderer_network_failure_is_retried_once(tmp_path: Path, monkeypatch) -> None:
    _store, config = pipeline_fixture(tmp_path)

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"status": "success", "output_path": str(tmp_path / "final.mp4")}

    class FakeClient:
        attempts = 0

        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, json):
            self.__class__.attempts += 1
            if self.__class__.attempts == 1:
                raise httpx.ConnectError("temporary outage", request=httpx.Request("POST", _url))
            assert json["job_id"] == "vid_12345678"
            return FakeResponse()

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("npd_worker.pipeline.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("npd_worker.pipeline.asyncio.sleep", no_sleep)

    result = await call_renderer(
        config,
        job_id="vid_12345678",
        manifest_path=tmp_path / "video-manifest.json",
        output_path=tmp_path / "final.mp4",
    )

    assert result["status"] == "success"
    assert FakeClient.attempts == 2


def test_strict_pilot_requires_real_logo(tmp_path: Path) -> None:
    config = _config(tmp_path, pilot_strict_assets=True)
    job_dir = tmp_path / "jobs" / "vid_12345678"
    job_dir.mkdir(parents=True)
    with pytest.raises(AssetResolutionError, match="required brand logo"):
        ensure_brand_logo(config, job_dir)


def test_openai_provider_selection_requires_key(tmp_path: Path) -> None:
    config = _config(tmp_path, tts_provider="openai", openai_api_key="")
    with pytest.raises(Exception, match="OPENAI_API_KEY"):
        get_tts_provider(config)


def test_preflight_accepts_real_logo_and_media(tmp_path: Path) -> None:
    asset_root = tmp_path / "assets"
    project = asset_root / "vinhomes-green-paradise"
    project.mkdir(parents=True)
    for index in range(5):
        (project / f"clip-{index}.jpg").write_bytes(b"fixture")
    logo = asset_root / "brand" / "npd-logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"logo")

    config = _config(tmp_path, asset_root=asset_root, logo_path=logo, pilot_strict_assets=True)
    result = validate_pilot_assets(
        config,
        project_folder="vinhomes-green-paradise",
        minimum_clips=5,
    )
    assert result.asset_count == 5
    assert result.logo_path == str(logo)


def test_preflight_rejects_empty_media(tmp_path: Path) -> None:
    asset_root = tmp_path / "assets"
    project = asset_root / "project"
    project.mkdir(parents=True)
    (project / "clip.jpg").write_bytes(b"")
    logo = asset_root / "brand" / "npd-logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"logo")
    config = _config(tmp_path, asset_root=asset_root, logo_path=logo)

    with pytest.raises(AssetResolutionError, match="empty media"):
        validate_pilot_assets(config, project_folder="project", minimum_clips=1)
