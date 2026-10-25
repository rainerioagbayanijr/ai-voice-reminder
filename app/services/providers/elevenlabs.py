import json
import logging
from urllib.parse import quote

import aiohttp

from app.core.config import Settings
from app.models import VoiceRequest
from app.services.providers.base import SpeechOptions, TTSFailure, allowed_voice, collect_audio

logger = logging.getLogger("reminder")


class ElevenLabsProvider:
    name = "elevenlabs"
    endpoint = "https://api.elevenlabs.io/v1/text-to-speech"

    def __init__(self, settings: Settings, *, session_factory=None):
        self.settings = settings
        # Test injection is code-only; there is no configurable outbound API host.
        self.session_factory = session_factory

    def options(self, request: VoiceRequest) -> SpeechOptions:
        voice = allowed_voice(
            request.voice,
            self.settings.elevenlabs_voice_id,
            self.settings.elevenlabs_allowed_voices or self.settings.elevenlabs_voice_id,
        )
        rate = request.rate or f"{(self.settings.elevenlabs_speed - 1) * 100:+.6g}%"
        speed = 1 + float(rate[:-1]) / 100
        if not 0.7 <= speed <= 1.2:
            raise ValueError("ElevenLabs speed must be between 0.7 and 1.2")
        volume = request.volume or "+0%"
        if int(volume[:-1]) != 0:
            raise ValueError("ElevenLabs does not expose the Edge volume control")
        return SpeechOptions(voice=voice, rate=rate, volume=volume)

    async def synthesize(self, text: str, options: SpeechOptions) -> bytes:
        payload = {
            "text": text,
            "model_id": self.settings.elevenlabs_model_id,
            "voice_settings": {
                "speed": round(1 + float(options.rate[:-1]) / 100, 6),
                "stability": self.settings.elevenlabs_stability,
                "similarity_boost": self.settings.elevenlabs_similarity_boost,
            },
        }
        if self.settings.elevenlabs_language_code:
            payload["language_code"] = self.settings.elevenlabs_language_code
        factory = self.session_factory or aiohttp.ClientSession
        try:
            async with factory(
                timeout=aiohttp.ClientTimeout(
                    total=self.settings.tts_timeout_seconds, connect=10, sock_read=20
                ),
                trust_env=False,
            ) as session:
                async with session.post(
                    f"{self.endpoint}/{quote(options.voice, safe='')}",
                    headers={
                        "xi-api-key": self.settings.elevenlabs_api_key.get_secret_value(),
                        "Accept": "audio/mpeg",
                    },
                    params={"output_format": "mp3_44100_128"},
                    json=payload,
                    allow_redirects=False,
                ) as response:
                    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                    if response.status != 200 or content_type not in {"audio/mpeg", "audio/mp3"}:
                        logger.warning(
                            json.dumps(
                                {
                                    "event": "speech_provider_failure",
                                    "provider": self.name,
                                    "http_status": response.status,
                                }
                            )
                        )
                        raise TTSFailure  # Never echo upstream bodies/headers/credentials.
                    return await collect_audio(
                        response.content.iter_chunked(65536), self.settings.max_audio_bytes
                    )
        except aiohttp.ClientError:
            raise TTSFailure from None
