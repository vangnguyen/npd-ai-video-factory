from __future__ import annotations

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
        hook = f"{request.topic}: điều gì đáng chú ý?"
        body = [
            f"Điểm một: tập trung vào thông tin thực tế của {request.project}.",
            "Điểm hai: đối chiếu sản phẩm, vị trí và trải nghiệm dự án.",
            "Điểm ba: chỉ sử dụng dữ liệu đã được cung cấp hoặc xác minh.",
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
