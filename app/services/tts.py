import asyncio

import edge_tts

from app.core.config import Settings
from app.models import VoiceRequest
from app.services.templates import Templates


class TTSBusy(Exception):
    pass


class TTSFailure(Exception):
    pass


class TTSService:
    def __init__(self, settings: Settings, templates: Templates):
        self.settings = settings
        self.templates = templates
        self.semaphore = asyncio.Semaphore(settings.max_concurrency)

    async def generate(self, request: VoiceRequest) -> bytes:
        voice = request.voice or self.settings.voice
        if voice not in self.settings.allowed_voices.split(","):
            raise ValueError("Voice is not enabled")
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=0.1)
        except TimeoutError as exc:
            raise TTSBusy from exc
        try:
            async with asyncio.timeout(self.settings.tts_timeout_seconds):
                communicator = edge_tts.Communicate(
                    self.templates.render("voice", request),
                    voice,
                    rate=request.rate or self.settings.rate,
                    volume=request.volume or self.settings.volume,
                    connect_timeout=10,
                    receive_timeout=20,
                )
                audio = bytearray()
                async for chunk in communicator.stream():
                    if chunk["type"] == "audio":
                        audio.extend(chunk["data"])
                        if len(audio) > self.settings.max_audio_bytes:
                            raise TTSFailure
                if not audio:
                    raise TTSFailure
                return bytes(audio)
        except (TimeoutError, TTSFailure):
            raise
        except Exception as exc:
            raise TTSFailure from exc
        finally:
            self.semaphore.release()
