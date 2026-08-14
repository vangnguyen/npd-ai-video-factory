from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import httpx
import pytest

from app.models import VideoJobCreate
from app.providers import (
    DeterministicContentProvider,
    OpenAIVietnameseTTSProvider,
    TTSNotConfiguredError,
)


def _wav_bytes(
    duration_seconds: float = 0.25,
    sample_rate: int = 16000,
    *,
    streaming_header: bool = False,
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * int(duration_seconds * sample_rate))
    payload = bytearray(buffer.getvalue())
    if streaming_header:
        payload[4:8] = b"\xff\xff\xff\xff"
        payload[40:44] = b"\xff\xff\xff\x7f"
    return bytes(payload)


@pytest.mark.asyncio
async def test_deterministic_content_uses_a_readable_project_name() -> None:
    request = VideoJobCreate.model_validate(
        {
            "topic": "Ba lý do nên chú ý Vinhomes Green Paradise tuần này",
            "project": "vinhomes-green-paradise",
            "video": {
                "duration_seconds": 45,
                "aspect": "9:16",
                "language": "vi",
                "template": "real-estate-short-v1",
            },
            "content": {
                "objective": "lead_generation",
                "audience": "khách hàng quan tâm bất động sản Cần Giờ",
                "tone": "thông tin, tin cậy, không phóng đại",
                "cta": "Đăng ký tham quan sa bàn",
            },
            "media": {
                "source": "local",
                "project_asset_folder": "vinhomes-green-paradise",
                "minimum_clips": 5,
                "allow_stock": False,
                "allow_ai_generation": False,
            },
        }
    )

    script = await DeterministicContentProvider().generate_script(request)

    assert "Vinhomes Green Paradise" in script.hook
    assert "vinhomes-green-paradise" not in script.full_narration
    assert len(script.body) == 4
    assert "tài liệu chính thức" in script.full_narration

    storyboard = await DeterministicContentProvider().generate_storyboard(request, script)
    assert len(storyboard.scenes) == 6
    assert [scene.narration for scene in storyboard.scenes] == [
        script.hook,
        *script.body,
        script.cta,
    ]


@pytest.mark.asyncio
async def test_openai_tts_uses_speech_endpoint_without_external_network(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "gpt-4o-mini-tts"
        assert payload["voice"] == "marin"
        assert payload["response_format"] == "wav"
        assert payload["input"] == "Xin chào Cần Giờ"
        assert "tự nhiên" in payload["instructions"]
        return httpx.Response(200, content=_wav_bytes())

    provider = OpenAIVietnameseTTSProvider(
        api_key="test-key",
        model="gpt-4o-mini-tts",
        voice="marin",
        instructions="Đọc tự nhiên và rõ ràng.",
        transport=httpx.MockTransport(handler),
    )
    output = tmp_path / "narration.wav"
    result = await provider.synthesize(
        text="Xin chào Cần Giờ",
        language="vi",
        output_path=output,
    )

    assert result.provider == "openai"
    assert result.voice == "marin"
    assert result.duration_seconds > 0
    assert output.is_file()


@pytest.mark.asyncio
async def test_openai_tts_measures_streaming_wav_from_actual_payload(tmp_path: Path) -> None:
    provider = OpenAIVietnameseTTSProvider(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=_wav_bytes(streaming_header=True))
        ),
    )

    result = await provider.synthesize(
        text="Xin chào",
        language="vi",
        output_path=tmp_path / "streaming.wav",
    )

    assert result.duration_seconds == pytest.approx(0.25)


def test_openai_tts_requires_api_key() -> None:
    with pytest.raises(TTSNotConfiguredError, match="OPENAI_API_KEY"):
        OpenAIVietnameseTTSProvider(api_key="")


@pytest.mark.asyncio
async def test_openai_tts_rejects_api_error_without_writing_file(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid credential"}})

    provider = OpenAIVietnameseTTSProvider(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    output = tmp_path / "narration.wav"

    with pytest.raises(RuntimeError, match="HTTP 401"):
        await provider.synthesize(text="Xin chào", language="vi", output_path=output)
    assert not output.exists()


@pytest.mark.asyncio
async def test_openai_tts_enforces_speech_input_limit(tmp_path: Path) -> None:
    provider = OpenAIVietnameseTTSProvider(
        api_key="test-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    with pytest.raises(ValueError, match="4096"):
        await provider.synthesize(text="x" * 4097, language="vi", output_path=tmp_path / "voice.wav")
