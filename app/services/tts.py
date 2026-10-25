"""Provider-independent rendering, validation, deadline and concurrency boundary."""

import asyncio

from app.core.config import Settings
from app.models import VoiceRequest
from app.services.providers.base import (
    SpeechProvider,
    is_mp3,
)
from app.services.providers.base import (
    TTSBusy as TTSBusy,
)
from app.services.providers.base import (
    TTSFailure as TTSFailure,
)
from app.services.templates import Templates


def build_provider(settings: Settings) -> SpeechProvider:
    if settings.tts_provider == "edge":
        from app.services.providers.edge import EdgeTTSProvider

        return EdgeTTSProvider(settings)
    if settings.tts_provider == "elevenlabs":
        from app.services.providers.elevenlabs import ElevenLabsProvider

        return ElevenLabsProvider(settings)
    raise ValueError("Unsupported speech provider")


class TTSService:
    def __init__(
        self, settings: Settings, templates: Templates, *, provider: SpeechProvider | None = None
    ):
        self.settings = settings
        self.templates = templates
        self.provider = provider if provider is not None else build_provider(settings)
        self.semaphore = asyncio.Semaphore(settings.max_concurrency)

    async def generate(self, request: VoiceRequest) -> bytes:
        options = self.provider.options(request)
        text = self.templates.render("voice", request)
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=0.1)
        except TimeoutError:
            raise TTSBusy from None
        try:
            async with asyncio.timeout(self.settings.tts_timeout_seconds):
                audio = await self.provider.synthesize(text, options)
                if not is_mp3(audio) or len(audio) > self.settings.max_audio_bytes:
                    raise TTSFailure
                return audio
        except (TimeoutError, TTSFailure):
            raise
        except Exception:
            raise TTSFailure from None
        finally:
            self.semaphore.release()
