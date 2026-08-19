from __future__ import annotations

import asyncio
import wave
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from .models import VideoJobCreate


class ScriptResult(BaseModel):
    title: str
    hook: str
    body: list[str]
    cta: str
    full_narration: str


class StoryboardScene(BaseModel):
    id: str
    order: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    role: str
    narration: str
    on_screen_text: str | None = None
    visual_query: str


class StoryboardResult(BaseModel):
    scenes: list[StoryboardScene]

    @property
    def duration_seconds(self) -> float:
        return sum(scene.duration_seconds for scene in self.scenes)


class VoiceResult(BaseModel):
    path: Path
    duration_seconds: float = Field(gt=0)
    provider: str
    voice: str


class ContentProvider(Protocol):
    async def generate_script(self, request: VideoJobCreate) -> ScriptResult: ...
    async def generate_storyboard(self, request: VideoJobCreate, script: ScriptResult) -> StoryboardResult: ...


class TTSProvider(Protocol):
    async def synthesize(self, *, text: str, language: str, output_path: Path) -> VoiceResult: ...


class DeterministicContentProvider:
    """Test/dev provider. Production LLM adapters must implement ContentProvider."""

    async def generate_script(self, request: VideoJobCreate) -> ScriptResult:
        project_name = request.project.replace("-", " ").title()
        hook = f"{request.topic}. Đây là ba điểm cần kiểm tra."
        body = [
            f"Thứ nhất, hãy tập trung vào thông tin thực tế của dự án {project_name}.",
            "Thứ hai, hãy đối chiếu loại sản phẩm, vị trí và trải nghiệm tại dự án.",
            "Thứ ba, chỉ sử dụng dữ liệu đã được cung cấp hoặc đã xác minh.",
            "Hãy hoàn tất các bước kiểm tra này trước khi đưa ra quyết định.",
        ]
        narration = " ".join([hook, *body, request.content.cta])
        return ScriptResult(title=request.topic, hook=hook, body=body, cta=request.content.cta, full_narration=narration)

    async def generate_storyboard(self, request: VideoJobCreate, script: ScriptResult) -> StoryboardResult:
        count = 6 if request.video.duration_seconds >= 30 else 4
        duration = request.video.duration_seconds / count
        roles = ["hook", "identity", "information", "evidence", "sales_angle", "cta"]
        narration_parts = [script.hook, *script.body, script.cta]
        scenes: list[StoryboardScene] = []
        for index in range(count):
            role = roles[index] if index < len(roles) else "information"
            narration = narration_parts[min(index, len(narration_parts) - 1)]
            scenes.append(
                StoryboardScene(
                    id=f"scene_{index + 1:02d}",
                    order=index + 1,
                    start_seconds=round(index * duration, 3),
                    duration_seconds=round(duration, 3),
                    role=role,
                    narration=narration,
                    on_screen_text=narration[:90],
                    visual_query=f"{request.project} {role}",
                )
            )
        # Avoid accumulated rounding drift in the final scene.
        scenes[-1].duration_seconds = round(request.video.duration_seconds - scenes[-1].start_seconds, 3)
        return StoryboardResult(scenes=scenes)


class TTSNotConfiguredError(RuntimeError):
    pass


class UnconfiguredVietnameseTTSProvider:
    """Explicit production-safe placeholder until a real Vietnamese TTS adapter is configured."""

    async def synthesize(self, *, text: str, language: str, output_path: Path) -> VoiceResult:
        if language != "vi":
            raise ValueError("Sprint 1 only supports Vietnamese TTS")
        raise TTSNotConfiguredError("Vietnamese TTS provider is not configured")


class EspeakVietnameseTTSProvider:
    """Offline Sprint 1 TTS adapter using espeak-ng inside the worker container."""

    def __init__(self, *, voice: str = "vi", rate: int = 145):
        self.voice = voice
        self.rate = rate

    async def synthesize(self, *, text: str, language: str, output_path: Path) -> VoiceResult:
        if language != "vi":
            raise ValueError("Sprint 1 only supports Vietnamese TTS")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            "espeak-ng",
            "-v",
            self.voice,
            "-s",
            str(self.rate),
            "-w",
            str(output_path),
            text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"espeak-ng failed: {detail or process.returncode}")

        with wave.open(str(output_path), "rb") as wav:
            duration = wav.getnframes() / float(wav.getframerate())
        if duration <= 0:
            raise RuntimeError("espeak-ng produced empty audio")
        return VoiceResult(
            path=output_path,
            duration_seconds=duration,
            provider="espeak-ng",
            voice=self.voice,
        )
