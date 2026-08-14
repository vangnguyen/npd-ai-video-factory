from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import shutil
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.assets import AssetResolutionError, LocalAssetResolver
from app.manifest import ManifestValidationError, build_manifest, persist_manifest, validate_manifest
from app.models import Artifact, JobError, JobRecord, JobStage, JobStatus, STAGE_ORDER
from app.providers import (
    DeterministicContentProvider,
    EspeakVietnameseTTSProvider,
    OpenAIVietnameseTTSProvider,
    ScriptResult,
    StoryboardResult,
    TTSProvider,
    TTSNotConfiguredError,
    UnconfiguredVietnameseTTSProvider,
)
from app.state import RedisJobStore


logger = logging.getLogger("npd-video-worker.pipeline")
T = TypeVar("T", bound=BaseModel)
JOB_ID_PATTERN = re.compile(r"^vid_[A-Za-z0-9_-]{4,76}$")
SUPPORTED_LOGO_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WorkerConfig:
    job_root: Path
    asset_root: Path
    schema_path: Path
    renderer_url: str
    brand_name: str
    logo_path: Path
    tts_provider: str
    espeak_voice: str
    espeak_rate: int
    renderer_timeout_seconds: float
    openai_api_key: str = ""
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "marin"
    openai_tts_instructions: str = ""
    openai_base_url: str = "https://api.openai.com"
    openai_tts_timeout_seconds: float = 120.0
    pilot_strict_assets: bool = False

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        return cls(
            job_root=Path(os.getenv("JOB_STORAGE_ROOT", "/workspace/storage/jobs")).resolve(),
            asset_root=Path(os.getenv("ASSET_STORAGE_ROOT", "/workspace/storage/assets")).resolve(),
            schema_path=Path(
                os.getenv(
                    "VIDEO_MANIFEST_SCHEMA_PATH",
                    "/workspace/packages/contracts/video-manifest.schema.json",
                )
            ).resolve(),
            renderer_url=os.getenv("RENDERER_URL", "http://renderer:3001").rstrip("/"),
            brand_name=os.getenv("NPD_BRAND_NAME", "Ngoc Phuong Dong"),
            logo_path=Path(
                os.getenv(
                    "NPD_LOGO_PATH",
                    "/workspace/storage/assets/brand/npd-logo.png",
                )
            ).resolve(),
            tts_provider=os.getenv("TTS_PROVIDER", "espeak").lower(),
            espeak_voice=os.getenv("ESPEAK_VOICE", "vi"),
            espeak_rate=int(os.getenv("ESPEAK_RATE", "145")),
            renderer_timeout_seconds=float(os.getenv("RENDERER_TIMEOUT_SECONDS", "600")),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_tts_model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip(),
            openai_tts_voice=os.getenv("OPENAI_TTS_VOICE", "marin").strip(),
            openai_tts_instructions=os.getenv(
                "OPENAI_TTS_INSTRUCTIONS",
                "Đọc tiếng Việt tự nhiên, rõ ràng, nhịp nhanh gọn và dứt khoát; "
                "phong cách tư vấn bất động sản chuyên nghiệp, giàu năng lượng "
                "nhưng không cường điệu; ngắt nghỉ ngắn giữa các ý.",
            ).strip(),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/"),
            openai_tts_timeout_seconds=float(os.getenv("OPENAI_TTS_TIMEOUT_SECONDS", "120")),
            pilot_strict_assets=_env_flag("PILOT_STRICT_ASSETS", False),
        )


class PipelineFailure(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        stage: JobStage,
        retryable: bool = False,
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.retryable = retryable
        self.details = details or []


class RendererUnavailable(RuntimeError):
    pass


class RendererFailed(RuntimeError):
    pass


class VideoQCError(RuntimeError):
    pass


def safe_job_dir(root: Path, job_id: str) -> Path:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError("invalid job id")
    root = root.resolve()
    candidate = (root / job_id).resolve()
    if candidate.parent != root:
        raise ValueError("job directory escaped storage root")
    return candidate


def artifact_url(job_id: str, name: str) -> str:
    return f"/api/v1/video-jobs/{job_id}/artifacts/{name}"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_model(path: Path, model_type: type[T]) -> T:
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


class NarrationCue(BaseModel):
    scene_id: str
    start_seconds: float
    end_seconds: float
    text: str


class NarrationTiming(BaseModel):
    duration_seconds: float
    cues: list[NarrationCue]


PCM_ACTIVITY_THRESHOLD = 128
NARRATION_START_PADDING_SECONDS = 0.15
NARRATION_END_PADDING_SECONDS = 0.20


def build_subtitles(timing: NarrationTiming) -> list[dict[str, Any]]:
    return [
        {
            "start_seconds": cue.start_seconds,
            "end_seconds": cue.end_seconds,
            "text": cue.text[:160],
        }
        for cue in timing.cues
        if cue.text.strip()
    ]


def _pcm16_samples(path: Path) -> tuple[array, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
            raise ValueError("Sprint 1 narration chunks must be mono 16-bit PCM WAV")
        sample_rate = wav.getframerate()
        samples = array("h")
        samples.frombytes(wav.readframes(wav.getnframes()))
    if sys.byteorder == "big":
        samples.byteswap()
    return samples, sample_rate


def _trim_pcm_activity(samples: array, sample_rate: int) -> array:
    active = [index for index, sample in enumerate(samples) if abs(sample) >= PCM_ACTIVITY_THRESHOLD]
    if not active:
        raise ValueError("TTS chunk contains no audible samples")
    padding = max(1, int(round(sample_rate * 0.04)))
    start = max(0, active[0] - padding)
    end = min(len(samples), active[-1] + padding + 1)
    return samples[start:end]


async def synthesize_timed_narration(
    provider: Any,
    *,
    storyboard: StoryboardResult,
    language: str,
    output_path: Path,
    timing_path: Path,
    duration_seconds: float,
) -> NarrationTiming:
    chunks: list[tuple[Any, array, int]] = []
    sample_rate: int | None = None
    for scene in storyboard.scenes:
        chunk_path = output_path.with_name(f"narration-{scene.id}.wav")
        await provider.synthesize(text=scene.narration, language=language, output_path=chunk_path)
        samples, chunk_rate = _pcm16_samples(chunk_path)
        if sample_rate is None:
            sample_rate = chunk_rate
        elif sample_rate != chunk_rate:
            raise ValueError("TTS chunks use inconsistent sample rates")
        chunks.append((scene, _trim_pcm_activity(samples, chunk_rate), chunk_rate))

    if sample_rate is None:
        raise ValueError("storyboard has no narration scenes")

    total_frames = int(round(duration_seconds * sample_rate))
    master = array("h", [0]) * total_frames
    cues: list[NarrationCue] = []
    for scene, samples, _chunk_rate in chunks:
        cue_start = round(scene.start_seconds + NARRATION_START_PADDING_SECONDS, 3)
        latest_end = scene.start_seconds + scene.duration_seconds - NARRATION_END_PADDING_SECONDS
        cue_end = cue_start + len(samples) / sample_rate
        if cue_end > latest_end + 0.001:
            raise ValueError(
                f"TTS narration for {scene.id} is {cue_end - cue_start:.3f}s and does not fit its scene"
            )
        start_frame = int(round(cue_start * sample_rate))
        end_frame = start_frame + len(samples)
        if end_frame > len(master):
            raise ValueError(f"TTS narration for {scene.id} exceeds the composition duration")
        master[start_frame:end_frame] = samples
        cues.append(
            NarrationCue(
                scene_id=scene.id,
                start_seconds=cue_start,
                end_seconds=round(cue_end, 3),
                text=scene.narration,
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames = array("h", master)
    if sys.byteorder == "big":
        frames.byteswap()
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames.tobytes())

    timing = NarrationTiming(duration_seconds=duration_seconds, cues=cues)
    write_json(timing_path, timing)
    validate_narration_audio(output_path, timing, expected_duration=duration_seconds)
    return timing


def validate_narration_audio(
    path: Path,
    timing: NarrationTiming,
    *,
    expected_duration: float,
) -> float:
    samples, sample_rate = _pcm16_samples(path)
    duration = len(samples) / float(sample_rate)
    if abs(duration - expected_duration) > 0.05:
        raise ValueError("narration master duration does not match the composition")
    previous_end = 0.0
    for cue in timing.cues:
        if cue.start_seconds < previous_end or cue.end_seconds <= cue.start_seconds:
            raise ValueError("narration cue timing is not monotonic")
        if cue.end_seconds > expected_duration + 0.001:
            raise ValueError("narration cue exceeds the composition duration")
        start = max(0, int(cue.start_seconds * sample_rate))
        end = min(len(samples), int(round(cue.end_seconds * sample_rate)))
        if not any(abs(sample) >= PCM_ACTIVITY_THRESHOLD for sample in samples[start:end]):
            raise ValueError(f"narration cue {cue.scene_id} contains no audible samples")
        previous_end = cue.end_seconds
    return duration


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(path: Path, subtitles: list[dict[str, Any]]) -> None:
    blocks: list[str] = []
    for index, item in enumerate(subtitles, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_srt_timestamp(float(item['start_seconds']))} --> {_srt_timestamp(float(item['end_seconds']))}",
                    str(item["text"]),
                ]
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")


def _read_wav_pcm(path: Path) -> tuple[tuple[int, int, int], bytes]:
    if not path.is_file() or path.stat().st_size <= 44:
        raise ValueError("audio artifact is missing or empty")
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frame_rate = wav.getframerate()
        if wav.getcomptype() != "NONE":
            raise ValueError("compressed WAV audio is not supported")
        chunks: list[bytes] = []
        while chunk := wav.readframes(65_536):
            chunks.append(chunk)
        frames = b"".join(chunks)
    frame_width = channels * sample_width
    if channels <= 0 or sample_width <= 0 or frame_rate <= 0 or len(frames) % frame_width:
        raise ValueError("audio artifact has invalid WAV framing")
    return (channels, sample_width, frame_rate), frames


def validate_wav(path: Path, *, expected_duration: float | None = None) -> float:
    (channels, sample_width, frame_rate), frames = _read_wav_pcm(path)
    duration = (len(frames) // (channels * sample_width)) / float(frame_rate)
    if duration <= 0:
        raise ValueError("audio duration is zero")
    if expected_duration is not None and abs(duration - expected_duration) > 0.1:
        raise ValueError(
            f"audio duration {duration:.3f}s does not match timeline {expected_duration:.3f}s"
        )
    return duration


async def synthesize_storyboard_voice(
    tts_provider: TTSProvider,
    *,
    storyboard: StoryboardResult,
    language: str,
    output_path: Path,
    lead_in_seconds: float = 0.15,
    max_speedup: float = 1.4,
) -> float:
    """Synthesize each unique scene and place it on the storyboard timeline."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = output_path.parent / "voice-scenes"
    parts_dir.mkdir(parents=True, exist_ok=True)
    cached: dict[tuple[str, int], tuple[tuple[int, int, int], bytes]] = {}
    scene_audio: list[tuple[Any, tuple[int, int, int], bytes]] = []
    try:
        for scene in storyboard.scenes:
            text = scene.narration.strip()
            if not text:
                continue
            voice_slot_ms = round((scene.duration_seconds - lead_in_seconds) * 1_000)
            cache_key = (text, voice_slot_ms)
            audio = cached.get(cache_key)
            if audio is None:
                part_path = parts_dir / f"{scene.id}.wav"
                await tts_provider.synthesize(
                    text=text,
                    language=language,
                    output_path=part_path,
                )
                audio = _read_wav_pcm(part_path)
                (channels, sample_width, frame_rate), frames = audio
                frame_width = channels * sample_width
                clip_duration = (len(frames) // frame_width) / float(frame_rate)
                voice_slot = scene.duration_seconds - lead_in_seconds
                if clip_duration > voice_slot:
                    target_duration = max(0.1, voice_slot - 0.04)
                    speedup = clip_duration / target_duration
                    if speedup > max_speedup:
                        raise ValueError(
                            f"scene {scene.id} narration requires {speedup:.3f}x speed, "
                            f"above the {max_speedup:.3f}x production limit"
                        )
                    fitted_path = parts_dir / f"{scene.id}.fit.wav"
                    process = await asyncio.create_subprocess_exec(
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(part_path),
                        "-filter:a",
                        f"atempo={speedup:.6f}",
                        str(fitted_path),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _stdout, stderr = await process.communicate()
                    if process.returncode != 0:
                        detail = stderr.decode("utf-8", errors="replace").strip()
                        raise RuntimeError(
                            f"ffmpeg voice timing failed: {detail or process.returncode}"
                        )
                    audio = _read_wav_pcm(fitted_path)
                    logger.info(
                        "voice_scene_fitted scene_id=%s speedup=%.3f",
                        scene.id,
                        speedup,
                    )
                cached[cache_key] = audio
            scene_audio.append((scene, *audio))

        if not scene_audio:
            raise ValueError("storyboard has no narration to synthesize")

        channels, sample_width, frame_rate = scene_audio[0][1]
        for _scene, audio_format, _frames in scene_audio[1:]:
            if audio_format != (channels, sample_width, frame_rate):
                raise ValueError("TTS provider returned inconsistent WAV formats")

        total_seconds = max(
            scene.start_seconds + scene.duration_seconds for scene in storyboard.scenes
        )
        total_frames = round(total_seconds * frame_rate)
        silence_sample = b"\x80" if sample_width == 1 else b"\x00" * sample_width
        silence_frame = silence_sample * channels
        timeline = bytearray(silence_frame * total_frames)

        for scene, _audio_format, frames in scene_audio:
            frame_width = channels * sample_width
            clip_frames = len(frames) // frame_width
            slot_start = round((scene.start_seconds + lead_in_seconds) * frame_rate)
            slot_end = round((scene.start_seconds + scene.duration_seconds) * frame_rate)
            if clip_frames > slot_end - slot_start:
                clip_duration = clip_frames / float(frame_rate)
                raise ValueError(
                    f"scene {scene.id} narration is {clip_duration:.3f}s, longer than its "
                    f"{scene.duration_seconds - lead_in_seconds:.3f}s voice slot"
                )
            byte_start = slot_start * frame_width
            timeline[byte_start : byte_start + len(frames)] = frames

        temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        with wave.open(str(temp_path), "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(sample_width)
            wav.setframerate(frame_rate)
            wav.writeframes(timeline)
        temp_path.replace(output_path)
        return validate_wav(output_path, expected_duration=total_seconds)
    finally:
        shutil.rmtree(parts_dir, ignore_errors=True)


def ensure_brand_logo(config: WorkerConfig, job_dir: Path) -> Path:
    if config.logo_path.is_file() and config.logo_path.stat().st_size > 0:
        if config.logo_path.suffix.lower() in SUPPORTED_LOGO_SUFFIXES:
            return config.logo_path
        if config.pilot_strict_assets:
            raise AssetResolutionError(
                f"brand logo has unsupported format: {config.logo_path.suffix or '<none>'}"
            )
    elif config.pilot_strict_assets:
        raise AssetResolutionError(f"required brand logo is missing: {config.logo_path}")

    placeholder = job_dir / "npd-logo-placeholder.svg"
    label = html.escape(config.brand_name)
    placeholder.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg' width='600' height='180' viewBox='0 0 600 180'>"
        "<rect width='600' height='180' rx='24' fill='#111111' fill-opacity='0.72'/>"
        f"<text x='300' y='104' text-anchor='middle' font-family='Arial,sans-serif' font-size='38' font-weight='700' fill='white'>{label}</text>"
        "</svg>",
        encoding="utf-8",
    )
    return placeholder


def validate_probe_payload(
    payload: dict[str, Any],
    *,
    expected_duration: float,
    require_audio: bool,
) -> dict[str, Any]:
    streams = payload.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video is None:
        raise VideoQCError("final output has no video stream")
    if int(video.get("width", 0)) != 1080 or int(video.get("height", 0)) != 1920:
        raise VideoQCError("final output is not 1080x1920")
    if video.get("codec_name") != "h264":
        raise VideoQCError(f"expected H.264 video, found {video.get('codec_name')}")
    if require_audio and audio is None:
        raise VideoQCError("final output has no audio stream")

    frame_rate = video.get("avg_frame_rate") or video.get("r_frame_rate")
    try:
        numerator, denominator = str(frame_rate).split("/", maxsplit=1)
        fps = float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise VideoQCError("final output frame rate is unavailable") from exc
    if abs(fps - 30.0) > 0.01:
        raise VideoQCError(f"expected 30 fps video, found {fps:.3f}")

    raw_duration = (payload.get("format") or {}).get("duration") or video.get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as exc:
        raise VideoQCError("final output duration is unavailable") from exc
    if abs(duration - expected_duration) > 3.0:
        raise VideoQCError(
            f"final duration {duration:.3f}s differs from expected {expected_duration:.3f}s"
        )
    return {
        "duration_seconds": round(duration, 3),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": round(fps, 3),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
    }


def validate_visual_luma_values(values: list[float]) -> dict[str, Any]:
    if not values:
        raise VideoQCError("final output has no visual luminance samples")
    dark_count = sum(value < 8.0 for value in values)
    dark_ratio = dark_count / len(values)
    if dark_ratio > 0.10:
        raise VideoQCError(
            f"final output central image area is black in {dark_ratio:.1%} of sampled seconds"
        )
    return {
        "visual_sample_count": len(values),
        "dark_visual_sample_ratio": round(dark_ratio, 4),
        "visual_luma_min": round(min(values), 3),
        "visual_luma_max": round(max(values), 3),
    }


def parse_volume_output(output: str) -> dict[str, float]:
    mean_match = re.search(r"mean_volume:\s*(-?(?:inf|\d+(?:\.\d+)?))\s*dB", output, re.I)
    peak_match = re.search(r"max_volume:\s*(-?(?:inf|\d+(?:\.\d+)?))\s*dB", output, re.I)
    if mean_match is None or peak_match is None:
        raise VideoQCError("final output audio volume metadata is unavailable")
    mean_db = float(mean_match.group(1))
    peak_db = float(peak_match.group(1))
    if peak_db < -35.0:
        raise VideoQCError(f"final output audio is effectively silent at {peak_db:.1f} dB peak")
    return {"audio_mean_db": round(mean_db, 3), "audio_peak_db": round(peak_db, 3)}


async def analyze_render_content(path: Path) -> dict[str, Any]:
    visual = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-vf",
        "fps=1,crop=iw*0.5:ih*0.4:iw*0.25:ih*0.3,signalstats,metadata=mode=print:file=-",
        "-an",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    visual_stdout, visual_stderr = await visual.communicate()
    if visual.returncode != 0:
        raise VideoQCError(
            f"ffmpeg visual inspection failed: {visual_stderr.decode('utf-8', errors='replace').strip()}"
        )
    luma_values = [
        float(value)
        for value in re.findall(
            r"lavfi\.signalstats\.YAVG=([0-9.eE+-]+)",
            visual_stdout.decode("utf-8", errors="replace"),
        )
    ]

    audio = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(path),
        "-vn",
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _audio_stdout, audio_stderr = await audio.communicate()
    if audio.returncode != 0:
        raise VideoQCError("ffmpeg could not decode the rendered audio stream")

    return {
        **validate_visual_luma_values(luma_values),
        **parse_volume_output(audio_stderr.decode("utf-8", errors="replace")),
    }


async def probe_video(path: Path, *, expected_duration: float, require_audio: bool) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 100_000:
        raise VideoQCError("final MP4 is missing or smaller than 100 KB")
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise VideoQCError(
            f"ffprobe failed: {stderr.decode('utf-8', errors='replace').strip()}"
        )
    payload = json.loads(stdout.decode("utf-8"))
    result = validate_probe_payload(
        payload,
        expected_duration=expected_duration,
        require_audio=require_audio,
    )
    result.update(await analyze_render_content(path))
    result["size_bytes"] = path.stat().st_size
    return result


def get_tts_provider(config: WorkerConfig):
    if config.tts_provider == "espeak":
        return EspeakVietnameseTTSProvider(
            voice=config.espeak_voice,
            rate=config.espeak_rate,
        )
    if config.tts_provider == "openai":
        return OpenAIVietnameseTTSProvider(
            api_key=config.openai_api_key,
            model=config.openai_tts_model,
            voice=config.openai_tts_voice,
            instructions=config.openai_tts_instructions,
            base_url=config.openai_base_url,
            timeout_seconds=config.openai_tts_timeout_seconds,
        )
    if config.tts_provider in {"none", "unconfigured"}:
        return UnconfiguredVietnameseTTSProvider()
    raise TTSNotConfiguredError(f"unknown TTS_PROVIDER={config.tts_provider}")


async def advance(
    store: RedisJobStore,
    job_id: str,
    *,
    stage: JobStage,
    progress: int,
) -> JobRecord:
    current = await store.get(job_id)
    if current is None:
        raise KeyError(job_id)
    if current.status in {JobStatus.AWAITING_REVIEW, JobStatus.FAILED}:
        return current
    if STAGE_ORDER[stage] < STAGE_ORDER[current.stage] or progress < current.progress:
        return current
    return await store.update_stage(
        job_id,
        status=JobStatus.RUNNING,
        stage=stage,
        progress=progress,
    )


async def register_artifact(
    store: RedisJobStore,
    job_id: str,
    *,
    kind: str,
    path: Path,
) -> None:
    await store.add_artifact(
        job_id,
        artifact=Artifact(
            kind=kind,
            name=path.name,
            url=artifact_url(job_id, path.name),
        ),
    )


async def call_renderer(
    config: WorkerConfig,
    *,
    job_id: str,
    manifest_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    payload = {
        "job_id": job_id,
        "manifest_path": str(manifest_path),
        "output_path": str(output_path),
    }
    timeout = httpx.Timeout(
        connect=10.0,
        read=config.renderer_timeout_seconds,
        write=30.0,
        pool=10.0,
    )
    last_network_error: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(2):
            try:
                response = await client.post(f"{config.renderer_url}/render", json=payload)
            except httpx.RequestError as exc:
                last_network_error = exc
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                raise RendererUnavailable(str(exc)) from exc

            if response.status_code < 400:
                try:
                    result = response.json()
                except ValueError as exc:
                    raise RendererFailed("renderer returned invalid JSON") from exc
                if result.get("status") != "success" or result.get("output_path") != str(output_path):
                    raise RendererFailed("renderer returned an invalid success response")
                return result
            try:
                body = response.json()
            except ValueError:
                body = {}
            error = body.get("error", {})
            retryable = bool(body.get("retryable") or error.get("retryable")) or response.status_code in {502, 503, 504}
            message = str(body.get("message") or error.get("message") or f"renderer returned HTTP {response.status_code}")
            if retryable and attempt == 0:
                await asyncio.sleep(2)
                continue
            if response.status_code in {502, 503, 504}:
                raise RendererUnavailable(message)
            raise RendererFailed(message)
    if last_network_error is not None:
        raise RendererUnavailable(str(last_network_error))


async def run_job(
    store: RedisJobStore,
    job_id: str,
    *,
    config: WorkerConfig,
) -> JobRecord | None:
    record = await store.get(job_id)
    if record is None:
        logger.warning("job_missing job_id=%s", job_id)
        return None
    if record.status in {JobStatus.AWAITING_REVIEW, JobStatus.FAILED}:
        logger.info("job_terminal_skip job_id=%s status=%s", job_id, record.status.value)
        return record

    job_dir = safe_job_dir(config.job_root, job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    request = record.request
    content_provider = DeterministicContentProvider()
    current_stage = JobStage.SCRIPTING

    try:
        request_path = job_dir / "request.json"
        if not request_path.is_file():
            write_json(request_path, request)
        await register_artifact(store, job_id, kind="request", path=request_path)

        script_path = job_dir / "script.json"
        try:
            script = load_model(script_path, ScriptResult)
        except Exception:
            current_stage = JobStage.SCRIPTING
            await advance(store, job_id, stage=current_stage, progress=10)
            try:
                script = await content_provider.generate_script(request)
            except Exception as exc:
                raise PipelineFailure(
                    code="CONTENT_PROVIDER_FAILED",
                    message="Content provider could not generate the script.",
                    stage=current_stage,
                    details=[{"type": type(exc).__name__}],
                ) from exc
            write_json(script_path, script)
        await register_artifact(store, job_id, kind="script", path=script_path)

        storyboard_path = job_dir / "storyboard.json"
        try:
            storyboard = load_model(storyboard_path, StoryboardResult)
        except Exception:
            current_stage = JobStage.STORYBOARDING
            await advance(store, job_id, stage=current_stage, progress=20)
            try:
                storyboard = await content_provider.generate_storyboard(request, script)
            except Exception as exc:
                raise PipelineFailure(
                    code="CONTENT_PROVIDER_FAILED",
                    message="Content provider could not generate the storyboard.",
                    stage=current_stage,
                    details=[{"type": type(exc).__name__}],
                ) from exc
            if abs(storyboard.duration_seconds - request.video.duration_seconds) > 0.1:
                raise PipelineFailure(
                    code="CONTENT_PROVIDER_FAILED",
                    message="storyboard duration does not match request",
                    stage=current_stage,
                )
            write_json(storyboard_path, storyboard)
        await register_artifact(store, job_id, kind="storyboard", path=storyboard_path)

        voice_path = job_dir / "narration.wav"
        timing_path = job_dir / "narration-timing.json"
        try:
            timing = load_model(timing_path, NarrationTiming)
            validate_narration_audio(
                voice_path,
                timing,
                expected_duration=float(request.video.duration_seconds),
            )
        except Exception:
            current_stage = JobStage.GENERATING_VOICE
            await advance(store, job_id, stage=current_stage, progress=30)
            try:
                tts_provider = get_tts_provider(config)
                timing = await synthesize_timed_narration(
                    tts_provider,
                    storyboard=storyboard,
                    language=request.video.language,
                    output_path=voice_path,
                    timing_path=timing_path,
                    duration_seconds=float(request.video.duration_seconds),
                )
            except Exception as exc:
                raise PipelineFailure(
                    code="TTS_PROVIDER_FAILED",
                    message="TTS provider could not generate narration audio.",
                    stage=current_stage,
                    details=[{"type": type(exc).__name__}],
                ) from exc
        await register_artifact(store, job_id, kind="audio", path=voice_path)
        await register_artifact(store, job_id, kind="metadata", path=timing_path)

        current_stage = JobStage.GENERATING_SUBTITLES
        await advance(store, job_id, stage=current_stage, progress=40)
        subtitles = build_subtitles(timing)
        subtitles_path = job_dir / "subtitles.srt"
        write_srt(subtitles_path, subtitles)
        await register_artifact(store, job_id, kind="subtitle", path=subtitles_path)

        current_stage = JobStage.RESOLVING_ASSETS
        await advance(store, job_id, stage=current_stage, progress=50)
        try:
            resolved_assets = LocalAssetResolver(config.asset_root).resolve(request, storyboard)
        except AssetResolutionError as exc:
            raise PipelineFailure(
                code="ASSET_RESOLUTION_FAILED",
                message="Local assets could not be resolved for every scene.",
                stage=current_stage,
                details=[{"type": type(exc).__name__}],
            ) from exc
        assets_path = job_dir / "resolved-assets.json"
        write_json(assets_path, [item.model_dump(mode="json") for item in resolved_assets])
        await register_artifact(store, job_id, kind="assets", path=assets_path)

        current_stage = JobStage.BUILDING_MANIFEST
        await advance(store, job_id, stage=current_stage, progress=60)
        manifest_path = job_dir / "video-manifest.json"
        manifest: dict[str, Any] | None = None
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                validate_manifest(manifest, config.schema_path)
            except Exception:
                manifest = None
        if manifest is None:
            try:
                logo_path = ensure_brand_logo(config, job_dir)
            except AssetResolutionError as exc:
                raise PipelineFailure(
                    code="ASSET_NOT_FOUND",
                    message=str(exc),
                    stage=current_stage,
                ) from exc
            try:
                manifest = build_manifest(
                    request=request,
                    storyboard=storyboard,
                    resolved_assets=resolved_assets,
                    logo_uri=str(logo_path),
                    voice_uri=str(voice_path),
                    subtitles=subtitles,
                )
                persist_manifest(manifest, manifest_path, config.schema_path)
            except ManifestValidationError as exc:
                raise PipelineFailure(
                    code="MANIFEST_VALIDATION_FAILED",
                    message="Video manifest validation failed.",
                    stage=current_stage,
                    details=[{"type": type(exc).__name__}],
                ) from exc
        await register_artifact(store, job_id, kind="manifest", path=manifest_path)

        final_path = job_dir / "final.mp4"
        qc: dict[str, Any] | None = None
        if final_path.is_file():
            try:
                qc = await probe_video(
                    final_path,
                    expected_duration=float(request.video.duration_seconds),
                    require_audio=True,
                )
            except VideoQCError:
                final_path.unlink(missing_ok=True)
                qc = None

        if qc is None:
            current_stage = JobStage.RENDERING
            await advance(store, job_id, stage=current_stage, progress=70)
            try:
                await call_renderer(
                    config,
                    job_id=job_id,
                    manifest_path=manifest_path,
                    output_path=final_path,
                )
            except RendererUnavailable as exc:
                raise PipelineFailure(
                    code="RENDERER_UNAVAILABLE",
                    message="Renderer service is unavailable after bounded retries.",
                    stage=current_stage,
                    retryable=True,
                    details=[{"type": type(exc).__name__}],
                ) from exc
            except RendererFailed as exc:
                raise PipelineFailure(
                    code="RENDER_FAILED",
                    message="Renderer could not produce the final video.",
                    stage=current_stage,
                    details=[{"type": type(exc).__name__}],
                ) from exc

            current_stage = JobStage.QUALITY_CHECK
            await advance(store, job_id, stage=current_stage, progress=95)
            try:
                qc = await probe_video(
                    final_path,
                    expected_duration=float(request.video.duration_seconds),
                    require_audio=True,
                )
            except VideoQCError as exc:
                raise PipelineFailure(
                    code="QC_FAILED",
                    message="Final video failed quality-control verification.",
                    stage=current_stage,
                    details=[{"type": type(exc).__name__}],
                ) from exc
        else:
            current_stage = JobStage.QUALITY_CHECK
            await advance(store, job_id, stage=current_stage, progress=95)

        qc_path = job_dir / "qc.json"
        write_json(qc_path, qc)
        await register_artifact(store, job_id, kind="video", path=final_path)
        await register_artifact(store, job_id, kind="qc", path=qc_path)
        completed = await store.update_stage(
            job_id,
            status=JobStatus.AWAITING_REVIEW,
            stage=JobStage.AWAITING_REVIEW,
            progress=100,
        )
        logger.info("job_awaiting_review job_id=%s", job_id)
        return completed

    except PipelineFailure as exc:
        logger.error(
            "job_failed job_id=%s stage=%s code=%s message=%s",
            job_id,
            exc.stage.value,
            exc.code,
            exc.message,
        )
        return await store.fail(
            job_id,
            error=JobError(
                code=exc.code,
                message=exc.message,
                failed_stage=exc.stage,
                retryable=exc.retryable,
                details=exc.details,
            ),
        )
    except Exception as exc:
        logger.exception("job_failed_unexpected job_id=%s", job_id)
        return await store.fail(
            job_id,
            error=JobError(
                code="INTERNAL_ERROR",
                message="Unexpected worker failure.",
                failed_stage=current_stage,
                retryable=False,
                details=[{"type": type(exc).__name__}],
            ),
        )
