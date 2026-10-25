import asyncio
import json

import aiohttp
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.models import VoiceRequest
from app.services.providers.edge import EdgeTTSProvider
from app.services.providers.elevenlabs import ElevenLabsProvider
from app.services.templates import Templates
from app.services.tts import TTSFailure, TTSService, build_provider
from tests.speech_fakes import SpeechResponse, SpeechSession
from tests.test_api import FakeConverter


@pytest.fixture
def eleven_settings():
    return Settings(
        reminder_api_key="test-api-" + "x" * 32,
        tts_provider="elevenlabs",
        elevenlabs_api_key="test-elevenlabs-key-not-live",
        elevenlabs_voice_id="testVoice123",
        elevenlabs_model_id="test_model",
        _env_file=None,
    )


def service(settings, session):
    return TTSService(
        settings,
        Templates(settings),
        provider=ElevenLabsProvider(
            settings,
            session_factory=session.factory,
        ),
    )


def test_default_edge_does_not_require_elevenlabs(settings):
    assert settings.tts_provider == "edge" and settings.elevenlabs_api_key is None
    assert isinstance(build_provider(settings), EdgeTTSProvider)


@pytest.mark.parametrize(
    "changes",
    [
        {"tts_provider": "unknown"},
        {"tts_provider": "elevenlabs"},
        {"tts_provider": "elevenlabs", "elevenlabs_api_key": "test-secret-value"},
        {"elevenlabs_speed": 0.69},
        {"elevenlabs_speed": 1.21},
        {"elevenlabs_voice_id": "../other?token=bad"},
        {"elevenlabs_language_code": "fil"},
        {"elevenlabs_stability": 2},
    ],
)
def test_invalid_provider_config_fails_closed_without_echoing_secrets(changes):
    with pytest.raises(ValidationError) as error:
        Settings(reminder_api_key="test-api-" + "x" * 32, _env_file=None, **changes)
    assert "test-secret-value" not in str(error.value)


def test_elevenlabs_factory_and_request_contract(eleven_settings, voice, monkeypatch):
    session = SpeechSession()
    monkeypatch.setattr("app.services.providers.elevenlabs.aiohttp.ClientSession", session.factory)
    assert isinstance(build_provider(eleven_settings), ElevenLabsProvider)
    tts = TTSService(eleven_settings, Templates(eleven_settings))
    audio = asyncio.run(tts.generate(VoiceRequest(**voice)))
    assert audio == b"ID3-test-mp3"
    assert len(session.calls) == 1 and session.closed and session.response.closed
    call = session.calls[0]
    assert call["url"] == "https://api.elevenlabs.io/v1/text-to-speech/testVoice123"
    assert call["headers"] == {"xi-api-key": "test-elevenlabs-key-not-live", "Accept": "audio/mpeg"}
    assert call["params"] == {"output_format": "mp3_44100_128"}
    assert call["allow_redirects"] is False
    assert session.options[0]["trust_env"] is False
    payload = call["json"]
    assert set(payload) == {"text", "model_id", "voice_settings"}
    assert "Hello Juan" in payload["text"]
    assert payload["model_id"] == "test_model"
    assert payload["voice_settings"] == {"speed": 0.85, "stability": 0.5, "similarity_boost": 0.75}


@pytest.mark.parametrize("http_status", [302, 401, 403, 429, 500])
def test_upstream_failure_is_sanitized_closed_and_not_retried(
    eleven_settings, voice, http_status, caplog
):
    session = SpeechSession(SpeechResponse(status=http_status))
    tts = service(eleven_settings, session)
    with pytest.raises(TTSFailure):
        asyncio.run(tts.generate(VoiceRequest(**voice)))
    assert len(session.calls) == 1
    assert not session.response.read_started
    assert session.closed and session.response.closed
    assert tts.semaphore._value == eleven_settings.max_concurrency
    events = [json.loads(r.message) for r in caplog.records if r.name == "reminder"]
    assert events == [
        {"event": "speech_provider_failure", "provider": "elevenlabs", "http_status": http_status}
    ]


@pytest.mark.parametrize(
    "chunks,content_type",
    [
        ([], "audio/mpeg"),
        ([b"ID3" + b"x" * 1024], "audio/mpeg"),
        ([b'{"private":"details"}'], "application/json"),
        ([b"not-mp3"], "audio/mpeg"),
    ],
)
def test_invalid_or_oversized_audio_is_rejected(eleven_settings, voice, chunks, content_type):
    eleven_settings.max_audio_bytes = 1024
    session = SpeechSession(SpeechResponse(chunks, content_type=content_type))
    tts = service(eleven_settings, session)
    with pytest.raises(TTSFailure):
        asyncio.run(tts.generate(VoiceRequest(**voice)))
    assert session.closed and session.response.closed
    assert tts.semaphore._value == eleven_settings.max_concurrency


def test_network_error_does_not_leak_provider_details(eleven_settings, voice):
    session = SpeechSession(
        SpeechResponse(error=aiohttp.ClientConnectionError("private key detail"))
    )
    with pytest.raises(TTSFailure) as error:
        asyncio.run(service(eleven_settings, session).generate(VoiceRequest(**voice)))
    assert "private" not in str(error.value) and session.closed
    assert error.value.__cause__ is None


def test_deadline_and_cancellation_release_capacity(eleven_settings, voice):
    eleven_settings.tts_timeout_seconds = 0.01
    session = SpeechSession(SpeechResponse(delay=1))
    tts = service(eleven_settings, session)
    with pytest.raises(TimeoutError):
        asyncio.run(tts.generate(VoiceRequest(**voice)))
    assert session.closed and session.response.closed
    assert tts.semaphore._value == eleven_settings.max_concurrency

    async def cancel():
        task = asyncio.create_task(tts.generate(VoiceRequest(**voice)))
        await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert tts.semaphore._value == eleven_settings.max_concurrency


@pytest.mark.parametrize(
    "changes",
    [
        {"voice": "fil-PH-BlessicaNeural"},
        {"voice": "../other"},
        {"rate": "-31%"},
        {"volume": "-5%"},
    ],
)
def test_unsupported_options_block_before_paid_request(eleven_settings, voice, changes):
    session = SpeechSession()
    with pytest.raises(ValueError):
        asyncio.run(
            service(eleven_settings, session).generate(VoiceRequest(**{**voice, **changes}))
        )
    assert not session.calls


def test_provider_voice_speed_and_language_overrides(eleven_settings, voice):
    eleven_settings.elevenlabs_allowed_voices = "testVoice123,otherVoice456"
    eleven_settings.elevenlabs_language_code = "en"
    session = SpeechSession()
    asyncio.run(
        service(eleven_settings, session).generate(
            VoiceRequest(
                **{**voice, "voice": "otherVoice456", "rate": "-30%", "volume": "+0%"},
            )
        )
    )
    call = session.calls[0]
    assert call["url"].endswith("/otherVoice456")
    assert call["json"]["voice_settings"]["speed"] == 0.7
    assert call["json"]["language_code"] == "en"


def test_model_and_allowlist_config_gates():
    config = dict(
        reminder_api_key="test-api-" + "x" * 32,
        tts_provider="elevenlabs",
        elevenlabs_api_key="not-a-live-key",
        elevenlabs_voice_id="voice123",
        elevenlabs_model_id="test_model",
        _env_file=None,
    )
    for changes in [
        {"elevenlabs_allowed_voices": "otherVoice"},
        {"elevenlabs_allowed_voices": "voice123,../other"},
        {"elevenlabs_model_id": "eleven_multilingual_v2", "elevenlabs_language_code": "en"},
    ]:
        with pytest.raises(ValidationError):
            Settings(**{**config, **changes})


def test_elevenlabs_uses_same_mp3_and_voice_note_api(eleven_settings, voice, monkeypatch, caplog):
    session = SpeechSession()
    monkeypatch.setattr("app.services.providers.elevenlabs.aiohttp.ClientSession", session.factory)
    converter = FakeConverter()
    headers = {"X-API-Key": eleven_settings.reminder_api_key.get_secret_value()}
    with TestClient(create_app(eleven_settings, converter=converter)) as api:
        mp3 = api.post("/api/v1/voice/generate", json=voice, headers=headers)
        ogg = api.post("/api/v1/voice/generate?audio_format=ogg_opus", json=voice, headers=headers)
        assert mp3.status_code == ogg.status_code == 200
        assert mp3.headers["content-type"] == "audio/mpeg"
        assert ogg.headers["content-type"] == "audio/ogg"
        assert converter.calls == [b"ID3-test-mp3"]
        calls = len(session.calls)
        for changes in [{"volume": "-5%"}, {"provider": "edge"}]:
            response = api.post(
                "/api/v1/voice/generate", json={**voice, **changes}, headers=headers
            )
            assert response.status_code == 422
        assert len(session.calls) == calls
    assert "test-elevenlabs-key-not-live" not in json.dumps([r.message for r in caplog.records])
