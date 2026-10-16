import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.tts import TTSBusy, TTSFailure


class FakeTTS:
    def __init__(self, error=None):
        self.error = error

    async def generate(self, request):
        if self.error:
            raise self.error
        return b"ID3fake-test-audio"


def client(settings, error=None):
    return TestClient(create_app(settings, tts=FakeTTS(error)))


def headers(settings):
    return {"X-API-Key": settings.reminder_api_key.get_secret_value()}


def test_auth_health_and_binary(settings, voice):
    with client(settings) as api:
        assert api.get("/health").json() == {"status": "ok"}
        assert api.post("/api/v1/voice/generate", json=voice).status_code == 401
        response = api.post("/api/v1/voice/generate", json=voice, headers=headers(settings))
        assert response.status_code == 200
        assert response.content == b"ID3fake-test-audio"
        assert response.headers["content-type"] == "audio/mpeg"
        assert "payment_reminder.mp3" in response.headers["content-disposition"]
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-request-id"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("first_name", ""),
        ("agent_name", "Alex\nBcc: other@example.com"),
        ("due_date", "tomorrow"),
        ("due_date", 0),
        ("rate", "-90%"),
        ("volume", "100%"),
        ("customer_id", "../../escape"),
        ("balance", "100"),
    ],
)
def test_validation_no_raw_input(settings, voice, field, value):
    voice[field] = value
    with client(settings) as api:
        response = api.post("/api/v1/voice/generate", json=voice, headers=headers(settings))
        assert response.status_code == 422
        assert "input" not in response.text
        assert "Juan" not in response.text


@pytest.mark.parametrize("field", ["first_name", "bank_name", "agent_name", "due_date"])
def test_missing_required(settings, voice, field):
    del voice[field]
    with client(settings) as api:
        assert (
            api.post("/api/v1/voice/generate", json=voice, headers=headers(settings)).status_code
            == 422
        )


@pytest.mark.parametrize(
    "error,code",
    [
        (TTSBusy(), 429),
        (TTSFailure("secret upstream error"), 502),
        (TimeoutError(), 504),
        (ValueError(), 422),
    ],
)
def test_sanitized_provider_errors(settings, voice, error, code):
    with client(settings, error) as api:
        response = api.post("/api/v1/voice/generate", json=voice, headers=headers(settings))
        assert response.status_code == code
        assert "secret" not in response.text


def test_preview_and_tracking_disabled(settings, voice):
    with client(settings) as api:
        preview = api.post("/api/v1/voice/preview", json=voice, headers=headers(settings))
        assert "Hello Juan" in preview.json()["script"]
        assert api.get("/api/v1/reminders", headers=headers(settings)).status_code == 503


def test_logs_do_not_contain_personal_data(settings, voice, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="reminder")
    with client(settings) as api:
        api.post("/api/v1/voice/generate", json=voice, headers=headers(settings))
    records = [json.loads(r.message) for r in caplog.records if r.name == "reminder"]
    assert records
    assert "Juan" not in json.dumps(records)
    assert settings.reminder_api_key.get_secret_value() not in json.dumps(records)


def test_database_outage_is_sanitized(settings, customer):
    class OfflineStore:
        def initialize(self):
            pass

        def claim(self, row):
            raise psycopg.OperationalError("private connection details")

    with TestClient(create_app(settings, tts=FakeTTS(), store=OfflineStore())) as api:
        response = api.post(
            "/api/v1/reminders/claim", json={"row": customer}, headers=headers(settings)
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "Tracking unavailable"}
