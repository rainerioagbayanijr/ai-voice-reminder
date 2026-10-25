"""Use the real API/converter with a local tone source instead of online speech."""

import asyncio
import json
import os
import urllib.error
import urllib.request

from app.main import create_app as application
from app.services.tts import TTSFailure


class LocalToneTTS:
    async def generate(self, request):
        def fetch():
            message = urllib.request.Request(
                os.environ["WHATSAPP_E2E_TTS_URL"],
                data=json.dumps(request.model_dump(mode="json")).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(message, timeout=5) as response:
                return response.read()

        try:
            return await asyncio.to_thread(fetch)
        except (OSError, urllib.error.URLError):
            raise TTSFailure from None


def create_app():
    return application(tts=LocalToneTTS())
