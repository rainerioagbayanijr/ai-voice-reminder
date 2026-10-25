from collections.abc import AsyncIterable
from dataclasses import dataclass
from typing import Protocol

from app.models import VoiceRequest


class TTSBusy(Exception):
    pass


class TTSFailure(Exception):
    pass


@dataclass(frozen=True)
class SpeechOptions:
    voice: str
    rate: str
    volume: str


class SpeechProvider(Protocol):
    name: str

    def options(self, request: VoiceRequest) -> SpeechOptions: ...

    async def synthesize(self, text: str, options: SpeechOptions) -> bytes:
        """Return bounded MP3 from rendered text and controls, not full customer rows."""
        ...


def allowed_voice(requested: str | None, default: str, allowlist: str) -> str:
    selected = requested if requested is not None else default
    if selected not in {v.strip() for v in allowlist.split(",") if v.strip()}:
        raise ValueError("Voice is not enabled")
    return selected


def is_mp3(audio: bytes) -> bool:
    return audio.startswith(b"ID3") or (
        len(audio) >= 2 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0
    )


async def collect_audio(chunks: AsyncIterable[bytes], max_bytes: int) -> bytes:
    audio = bytearray()
    async for chunk in chunks:
        audio.extend(chunk)
        if len(audio) > max_bytes:
            raise TTSFailure
    if not audio:
        raise TTSFailure
    return bytes(audio)
