import edge_tts

from app.core.config import Settings
from app.models import VoiceRequest
from app.services.providers.base import SpeechOptions, allowed_voice, collect_audio


class EdgeTTSProvider:
    name = "edge"

    def __init__(self, settings: Settings):
        self.settings = settings

    def options(self, request: VoiceRequest) -> SpeechOptions:
        return SpeechOptions(
            voice=allowed_voice(request.voice, self.settings.voice, self.settings.allowed_voices),
            rate=request.rate or self.settings.rate,
            volume=request.volume or self.settings.volume,
        )

    async def synthesize(self, text: str, options: SpeechOptions) -> bytes:
        communicator = edge_tts.Communicate(
            text,
            options.voice,
            rate=options.rate,
            volume=options.volume,
            connect_timeout=10,
            receive_timeout=20,
        )

        async def chunks():
            async for chunk in communicator.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]

        return await collect_audio(chunks(), self.settings.max_audio_bytes)
