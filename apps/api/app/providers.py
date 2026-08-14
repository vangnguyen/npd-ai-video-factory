from __future__ import annotations

import asyncio
import wave
from pathlib import Path
from typing import Protocol

import httpx
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
        project_name = " ".join(part.capitalize() for part in request.project.split("-"))
        hook = f"Quan tâm {project_name}? Đừng chỉ nhìn phối cảnh."
        body = [
            "Một: xem sa bàn để hiểu quy hoạch và vị trí từng phân khu.",
            "Hai: chọn sản phẩm phù hợp nhu cầu ở, nghỉ dưỡng hay đầu tư.",
            "Ba: đối chiếu thông tin bằng tài liệu chính thức trước khi xuống tiền.",
            "Xem trực tiếp giúp bạn hỏi đúng và so sánh dễ hơn.",
        ]
        narration = " ".join([hook, *body, request.content.cta])
        return ScriptResult(title=request.topic, hook=hook, body=body, cta=request.content.cta, full_narration=narration)

    async def generate_storyboard(self, request: VideoJobCreate, script: ScriptResult) -> StoryboardResult:
        count = 6 if request.video.duration_seconds >= 30 else 4
        duration = request.video.duration_seconds / count
        roles = ["hook", "identity", "information", "evidence", "sales_angle", "cta"]
        narration_parts = (
            [script.hook, *script.body, script.cta]
            if count == 6
            else [script.hook, script.body[0], script.body[2], script.cta]
        )
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
        scenes[-1].duration_seconds = round(request.video.duration_seconds - scenes[-1].start_seconds, 3)
        return StoryboardResult(scenes=scenes)


class TTSNotConfiguredError(RuntimeError):
    pass


class UnconfiguredVietnameseTTSProvider:
    async def synthesize(self, *, text: str, language: str, output_path: Path) -> VoiceResult:
        if language != "vi":
            raise ValueError("Only Vietnamese TTS is configured for this pipeline")
        raise TTSNotConfiguredError("Vietnamese TTS provider is not configured")


class EspeakVietnameseTTSProvider:
    """Offline CI/dev TTS adapter using espeak-ng inside the worker container."""

    def __init__(self, *, voice: str = "vi", rate: int = 145):
        self.voice = voice
        self.rate = rate

    async def synthesize(self, *, text: str, language: str, output_path: Path) -> VoiceResult:
        if language != "vi":
            raise ValueError("Only Vietnamese TTS is configured for this pipeline")
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

        duration = _wav_duration(output_path)
        return VoiceResult(
            path=output_path,
            duration_seconds=duration,
            provider="espeak-ng",
            voice=self.voice,
        )


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        frame_rate = wav.getframerate()
        frame_width = wav.getnchannels() * wav.getsampwidth()
        chunks: list[bytes] = []
        while chunk := wav.readframes(65_536):
            chunks.append(chunk)
        frames = b"".join(chunks)
    if frame_rate <= 0 or frame_width <= 0 or len(frames) % frame_width:
        raise RuntimeError("TTS provider produced an invalid WAV payload")
    duration = (len(frames) // frame_width) / float(frame_rate)
    if duration <= 0:
        raise RuntimeError("TTS provider produced empty audio")
    return duration


class OpenAIVietnameseTTSProvider:
    """Production TTS adapter for OpenAI's /v1/audio/speech endpoint.

    CI tests inject an httpx MockTransport, so no external request is required.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini-tts",
        voice: str = "marin",
        instructions: str = "",
        base_url: str = "https://api.openai.com",
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key.strip():
            raise TTSNotConfiguredError("OPENAI_API_KEY is required when TTS_PROVIDER=openai")
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.instructions = instructions.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def synthesize(self, *, text: str, language: str, output_path: Path) -> VoiceResult:
        if language != "vi":
            raise ValueError("Only Vietnamese TTS is configured for this pipeline")
        text = text.strip()
        if not text:
            raise ValueError("TTS input text is empty")
        if len(text) > 4096:
            raise ValueError("TTS input exceeds the 4096-character speech endpoint limit")

        payload: dict[str, object] = {
            "model": self.model,
            "voice": self.voice,
            "input": text,
            "response_format": "wav",
        }
        if self.instructions:
            payload["instructions"] = self.instructions

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.timeout_seconds, connect=15.0)
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=self.transport,
        ) as client:
            try:
                response = await client.post("/v1/audio/speech", headers=headers, json=payload)
            except httpx.RequestError as exc:
                raise RuntimeError(f"OpenAI TTS request failed: {exc}") from exc

        if response.status_code >= 400:
            message = f"HTTP {response.status_code}"
            try:
                body = response.json()
                api_message = (body.get("error") or {}).get("message")
                if api_message:
                    message = f"{message}: {api_message}"
            except ValueError:
                pass
            raise RuntimeError(f"OpenAI TTS failed: {message}")

        if not response.content:
            raise RuntimeError("OpenAI TTS returned an empty audio body")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        temp_path.write_bytes(response.content)
        try:
            duration = _wav_duration(temp_path)
            temp_path.replace(output_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return VoiceResult(
            path=output_path,
            duration_seconds=duration,
            provider="openai",
            voice=self.voice,
        )
