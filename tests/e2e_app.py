"""Only the provider boundary is mocked; real API, database, n8n and SMTP nodes."""

import os

from app.main import create_app as production_app
from app.services.tts import TTSFailure


class FixtureTTS:
    async def generate(self, request):
        if os.getenv("E2E_TTS_FAIL") == "true":
            raise TTSFailure
        # Not playable speech. Tests explicitly assert transport and personalization.
        return b"ID3-test-fixture-" + request.first_name.encode()


def create_app():
    if os.getenv("E2E_LIVE") == "true":
        return production_app()
    return production_app(tts=FixtureTTS())
