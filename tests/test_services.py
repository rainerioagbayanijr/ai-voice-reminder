import asyncio

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models import Customer, VoiceRequest
from app.services.templates import Templates
from app.services.tts import TTSBusy, TTSFailure, TTSService


def test_customer_and_template(settings, customer):
    valid = Customer.model_validate(customer)
    assert valid.reminder_eligible is True
    templates = Templates(settings)
    script = templates.render("voice", valid.voice_request())
    assert "Hello Juan." in script
    assert "Alex from Example Fictional Bank" in script
    assert "November 15, 2026" in script
    assert valid.email not in script
    assert valid.phone not in script


@pytest.mark.parametrize("month,expected", [(1, "January"), (11, "November"), (12, "December")])
def test_filipino_templates_with_english_dates(settings, customer, month, expected):
    settings.language = "fil"
    customer["due_date"] = f"2026-{month:02d}-15"
    valid = Customer.model_validate(customer)
    templates = Templates(settings)
    for name in ("voice", "email", "subject"):
        text = templates.render(name, valid.voice_request())
        assert "{" not in text
        assert valid.bank_name in text
        assert valid.email not in text
        assert valid.phone not in text
        if name != "subject":
            assert valid.first_name in text
            expected_date = (
                f"{expected} fifteenth, two thousand twenty-six"
                if name == "voice"
                else f"{expected} 15, 2026"
            )
            assert expected_date in text
    assert "calling from" in templates.render("voice", valid.voice_request()).lower()


def test_filipino_voice_adapter(settings, voice, monkeypatch):
    settings.language = "fil"
    settings.voice = "fil-PH-BlessicaNeural"
    settings.allowed_voices += ",fil-PH-BlessicaNeural"
    calls = []

    class Communicator:
        def __init__(self, text, selected_voice, **kwargs):
            calls.append((text, selected_voice))

        async def stream(self):
            yield {"type": "audio", "data": b"ID3filipino"}

    monkeypatch.setattr("app.services.providers.edge.edge_tts.Communicate", Communicator)
    service = TTSService(settings, Templates(settings))
    assert asyncio.run(service.generate(VoiceRequest(**voice))) == b"ID3filipino"
    assert calls[0][1] == "fil-PH-BlessicaNeural"
    assert "November fifteenth, two thousand twenty-six" in calls[0][0]


def test_requested_agent_introduction_with_english_date(settings, voice):
    settings.language = "fil"
    voice.update(agent_name="Rain from Test Company", bank_name="Test Bank")
    script = Templates(settings).render("voice", VoiceRequest(**voice))
    assert script.startswith(
        "Hi, this is Rain from Test Company. Calling from Test Bank, "
        "regarding your payment due on November fifteenth, two thousand twenty-six."
    )
    assert "Juan, isang magalang na paalala" in script
    assert "Nobyembre" not in script


@pytest.mark.parametrize(
    "field,value",
    [
        ("email", "bad"),
        ("email", "one@example.com,two@example.com"),
        ("email", "one@example.com\nBcc: two@example.com"),
        ("due_date", "11/15/2026"),
        ("reminder_eligible", "yes"),
        ("reminder_eligible", ""),
        ("first_name", "<speak>Hi</speak>"),
    ],
)
def test_invalid_customer(customer, field, value):
    customer[field] = value
    with pytest.raises(ValidationError):
        Customer.model_validate(customer)


def test_config_recipient_gate():
    with pytest.raises(ValidationError):
        Settings(reminder_api_key="x" * 32, dry_run=False, _env_file=None)


def test_template_rejects_attributes(settings, tmp_path):
    folder = tmp_path / "en"
    folder.mkdir()
    (folder / "voice.txt").write_text("{first_name.__class__}")
    settings.template_dir = tmp_path
    with pytest.raises(ValueError):
        Templates(settings)


def test_edge_adapter_and_prosody(settings, voice, monkeypatch):
    calls = []

    class Communicator:
        def __init__(self, text, selected_voice, **kwargs):
            calls.append((text, selected_voice, kwargs))

        async def stream(self):
            yield {"type": "WordBoundary", "text": "Hello"}
            yield {"type": "audio", "data": b"ID3"}
            yield {"type": "audio", "data": b"audio"}

    monkeypatch.setattr("app.services.providers.edge.edge_tts.Communicate", Communicator)
    service = TTSService(settings, Templates(settings))
    assert asyncio.run(service.generate(VoiceRequest(**voice))) == b"ID3audio"
    assert calls[0][1] == "en-US-JennyNeural"
    assert calls[0][2]["rate"] == "-15%"
    assert calls[0][2]["volume"] == "-5%"
    assert "Juan" in calls[0][0]


@pytest.mark.parametrize("behavior", ["empty", "error", "timeout", "oversize"])
def test_edge_failure_cleanup(settings, voice, monkeypatch, behavior):
    settings.tts_timeout_seconds = 0.01
    settings.max_audio_bytes = 1024

    class Communicator:
        def __init__(self, *args, **kwargs):
            pass

        async def stream(self):
            if behavior == "error":
                raise RuntimeError("private provider response")
            if behavior == "timeout":
                await asyncio.sleep(0.1)
            if behavior == "oversize":
                yield {"type": "audio", "data": b"x" * 1025}
            if False:
                yield

    monkeypatch.setattr("app.services.providers.edge.edge_tts.Communicate", Communicator)
    service = TTSService(settings, Templates(settings))
    with pytest.raises(TimeoutError if behavior == "timeout" else TTSFailure):
        asyncio.run(service.generate(VoiceRequest(**voice)))
    assert service.semaphore._value == settings.max_concurrency


def test_concurrency_and_voice_allowlist(settings, voice):
    service = TTSService(settings, Templates(settings))
    voice["voice"] = "unapproved"
    with pytest.raises(ValueError):
        asyncio.run(service.generate(VoiceRequest(**voice)))

    async def busy():
        for _ in range(settings.max_concurrency):
            await service.semaphore.acquire()
        with pytest.raises(TTSBusy):
            await service.generate(VoiceRequest(**{**voice, "voice": None}))

    asyncio.run(busy())
