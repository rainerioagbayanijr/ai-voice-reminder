"""Live, fictional-only provider check. Requires internet; sends no email."""

import asyncio
from pathlib import Path

from app.core.config import Settings
from app.models import VoiceRequest
from app.services.templates import Templates
from app.services.tts import TTSService


async def main():
    settings = Settings(reminder_api_key="smoke-only-" + "x" * 32, _env_file=None)
    service = TTSService(settings, Templates(settings))
    folder = Path("previews")
    folder.mkdir(exist_ok=True)
    outputs = []
    for name in ("Juan", "Maria"):
        request = VoiceRequest(
            customer_id=f"SMOKE-{name}",
            first_name=name,
            bank_name="Example Fictional Bank",
            agent_name="Alex",
            due_date="2026-11-15",
        )
        audio = await service.generate(request)
        assert len(audio) > 1000
        assert audio[:3] == b"ID3" or (audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)
        path = folder / f"smoke-{name.lower()}.mp3"
        path.write_bytes(audio)
        outputs.append(audio)
        print(f"Generated {path}: {len(audio)} bytes")
    assert outputs[0] != outputs[1], "Personalized audio should differ"


if __name__ == "__main__":
    asyncio.run(main())
