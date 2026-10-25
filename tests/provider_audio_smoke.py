"""Run in the API image with --network none; real codecs, both mocked speech providers."""

import asyncio
import json
import subprocess
import sys

sys.path.insert(0, "/srv")

from app.core.config import Settings  # noqa: E402
from app.models import VoiceRequest  # noqa: E402
from app.services.audio import AudioConverter  # noqa: E402
from app.services.providers.edge import EdgeTTSProvider  # noqa: E402
from app.services.providers.elevenlabs import ElevenLabsProvider  # noqa: E402
from app.services.templates import Templates  # noqa: E402
from app.services.tts import TTSService  # noqa: E402
from tests.speech_fakes import SpeechResponse, SpeechSession  # noqa: E402


async def main():
    tone = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=0.25",
            "-c:a",
            "libmp3lame",
            "-f",
            "mp3",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout

    class ToneEdge(EdgeTTSProvider):
        async def synthesize(self, text, options):
            assert "Juan" in text and options.voice == "en-US-JennyNeural"
            return tone

    report = []
    for name in ("edge", "elevenlabs"):
        settings = Settings(
            reminder_api_key="fixture-" + "x" * 32,
            tts_provider=name,
            elevenlabs_api_key="test-key-not-live",
            elevenlabs_voice_id="fixtureVoice",
            elevenlabs_model_id="fixtureModel",
            _env_file=None,
        )
        session = SpeechSession(SpeechResponse([tone]))
        provider = (
            ToneEdge(settings)
            if name == "edge"
            else ElevenLabsProvider(
                settings,
                session_factory=session.factory,
            )
        )
        tts = TTSService(settings, Templates(settings), provider=provider)
        request = VoiceRequest(
            customer_id="FIXTURE",
            first_name="Juan",
            agent_name="Rain",
            bank_name="Test Bank",
            due_date="2026-11-15",
        )
        mp3 = await tts.generate(request)
        ogg = await AudioConverter(settings).to_opus(mp3)
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name,sample_rate,channels",
                "-of",
                "json",
                "-i",
                "pipe:0",
            ],
            input=ogg,
            capture_output=True,
            check=True,
        )
        stream = json.loads(probe.stdout)["streams"][0]
        assert stream == {"codec_name": "opus", "sample_rate": "48000", "channels": 1}
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "null", "-"],
            input=ogg,
            capture_output=True,
            check=True,
        )
        if name == "elevenlabs":
            assert len(session.calls) == 1 and "Juan" in session.calls[0]["json"]["text"]
            assert session.calls[0]["params"]["output_format"] == "mp3_44100_128"
        report.append(
            {
                "provider": name,
                "mp3_bytes": len(mp3),
                "ogg_bytes": len(ogg),
                "decoded": True,
                **stream,
            }
        )
    print(json.dumps({"real_codec_checks": report, "external_requests": 0}))


if __name__ == "__main__":
    asyncio.run(main())
