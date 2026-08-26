from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from app.providers import OpenAIVietnameseTTSProvider


async def main() -> int:
    enabled = os.getenv("RUN_EXTERNAL_TTS_SMOKE", "").strip().lower() in {"1", "true", "yes", "on"}
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not enabled:
        print("SKIP: set RUN_EXTERNAL_TTS_SMOKE=1 to allow the external TTS smoke request")
        return 0
    if not api_key:
        print("SKIP: OPENAI_API_KEY is not configured")
        return 0

    provider = OpenAIVietnameseTTSProvider(
        api_key=api_key,
        model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        voice=os.getenv("OPENAI_TTS_VOICE", "marin"),
        instructions=os.getenv(
            "OPENAI_TTS_INSTRUCTIONS",
            "Đọc tiếng Việt tự nhiên, rõ ràng, đáng tin cậy và chuyên nghiệp.",
        ),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com"),
        timeout_seconds=float(os.getenv("OPENAI_TTS_TIMEOUT_SECONDS", "120")),
    )

    with tempfile.TemporaryDirectory(prefix="npd-tts-smoke-") as directory:
        output = Path(directory) / "smoke.wav"
        result = await provider.synthesize(
            text="Ngọc Phương Đông kiểm tra giọng đọc tiếng Việt cho hệ thống video tự động.",
            language="vi",
            output_path=output,
        )
        if not output.is_file() or output.stat().st_size <= 44:
            raise RuntimeError("TTS smoke output is missing or empty")
        print(
            f"PASS: provider={result.provider} voice={result.voice} "
            f"duration={result.duration_seconds:.2f}s bytes={output.stat().st_size}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
