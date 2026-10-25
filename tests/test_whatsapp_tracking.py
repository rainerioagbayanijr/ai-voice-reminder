import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import create_app
from app.models import WhatsAppClaimRequest, WhatsAppOutcomeRequest, WhatsAppReserveRequest
from app.services.templates import Templates
from app.services.tracking import StateConflict
from app.services.whatsapp import (
    RoutingBlocked,
    WhatsAppStore,
    normalize_phone,
    prepare_whatsapp_batch,
    reply_window,
)


def recent_hello():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def request_data(customer):
    return {
        "row": {**customer, "last_hello_at_utc": recent_hello()},
        "institution_id": "test-bank",
        "routing_mode": "test",
        "phone_number_id": "123456789012345",
        "test_recipient": "639171234567",
        "last_hello_at_utc": recent_hello(),
    }


@pytest.fixture
def wa(settings):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    settings.database_url = SecretStr(url)
    settings.tenant_id = "test-" + uuid4().hex
    settings.whatsapp_test_recipient = "+639171234567"
    settings.whatsapp_test_recipient_verified = True
    settings.retry_delay_seconds = 0
    repository = WhatsAppStore(settings, Templates(settings))
    repository.test_ids = set()
    repository.initialize()
    yield repository
    with repository.connect() as conn:
        for reminder_id in repository.test_ids:
            conn.execute("DELETE FROM whatsapp_events WHERE reminder_id=%s", (reminder_id,))
            conn.execute("DELETE FROM whatsapp_reminders WHERE reminder_id=%s", (reminder_id,))


def claim(wa, data):
    result = wa.claim(WhatsAppClaimRequest.model_validate(data))
    if "reminder_id" in result:
        wa.test_ids.add(result["reminder_id"])
    return result


def reserve(wa, result, **changes):
    return wa.reserve(
        result["reminder_id"],
        WhatsAppReserveRequest(
            **{
                "token": result["token"],
                "recipient": result["recipient"],
                "media_id": "12345",
                **changes,
            }
        ),
    )


def outcome(wa, result, status, error=None, message=None):
    return wa.outcome(
        result["reminder_id"],
        WhatsAppOutcomeRequest(
            token=result["token"],
            status=status,
            error_code=error,
            message_id=message,
        ),
    )


@pytest.mark.parametrize("value", ["09171234567", "63917 1234567", "1,2", "", None, "1234567"])
def test_invalid_phones(value):
    with pytest.raises(ValueError):
        normalize_phone(value)


def test_phone_and_window_validation():
    assert normalize_phone("+639171234567") == "639171234567"
    assert reply_window(recent_hello()) > datetime.now(timezone.utc)
    for value in [
        "",
        "2026-01-01T00:00:00",
        "bad",
        None,
        (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    ]:
        with pytest.raises(ValueError):
            reply_window(value)


def test_prepare_preserves_per_customer_phone_without_email(customer):
    customer = {**customer, "last_hello_at_utc": recent_hello()}
    rows = [customer, {**customer, "customer_id": "C2", "phone": "+639172222222"}, customer]
    prepared = prepare_whatsapp_batch(rows)
    assert prepared[0]["row"]["phone"] == customer["phone"]
    assert prepared[1]["row"]["phone"] == "+639172222222"
    assert prepared[2]["reason"] == "duplicate_in_batch"
    assert "email" not in prepared[0]["row"]
    assert prepared[0]["row"]["last_hello_at_utc"] == customer["last_hello_at_utc"]


def test_customer_mode_is_blocked_before_database(settings, request_data):
    wa = WhatsAppStore(settings, Templates(settings))
    request_data["routing_mode"] = "customer"
    with pytest.raises(RoutingBlocked):
        wa.claim(WhatsAppClaimRequest(**request_data))


def test_whatsapp_http_validation_and_disabled_tracking(settings, request_data):
    headers = {"X-API-Key": settings.reminder_api_key.get_secret_value()}
    with TestClient(create_app(settings)) as api:
        url = "/api/v1/whatsapp/reminders/claim"
        assert api.post(url, json=request_data).status_code == 401
        assert api.post(url, json=request_data, headers=headers).status_code == 503
        assert api.get("/api/v1/whatsapp/reminders", headers=headers).status_code == 503
    with TestClient(create_app(settings, whatsapp_store=object())) as api:
        bad = {**request_data, "routing_mode": "unrestricted"}
        response = api.post(url, json=bad, headers=headers)
        assert response.status_code == 422 and "Juan" not in response.text


def test_concurrent_claims_and_restart_persistence(wa, request_data):
    request = WhatsAppClaimRequest(**request_data)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: wa.claim(request), range(8)))
    wa.test_ids.update(r["reminder_id"] for r in results)
    assert sum(r["proceed"] for r in results) == 1
    winner = next(r for r in results if r["proceed"])
    assert winner["recipient"] != request_data["row"]["phone"].removeprefix("+")
    reserve(wa, winner)
    outcome(wa, winner, "submitted", message="wamid.test")
    restarted = WhatsAppStore(wa.settings, wa.templates)
    restarted.initialize()
    assert not restarted.claim(request)["proceed"]
    assert restarted.history(1)[0]["message_id"] == "wamid.test"


def test_test_recipient_cannot_be_overridden(wa, request_data):
    request_data["test_recipient"] = "639172222222"
    with pytest.raises(RoutingBlocked):
        claim(wa, request_data)
    wa.settings.whatsapp_test_recipient_verified = False
    with pytest.raises(RoutingBlocked):
        claim(wa, request_data)


def test_customer_mode_uses_each_csv_phone_and_timestamp(wa, request_data):
    wa.settings.whatsapp_customer_routing_enabled = True
    request_data["routing_mode"] = "customer"
    first = claim(wa, request_data)
    request_data["row"].update(customer_id="C2", first_name="Maria", phone="+639172222222")
    second = claim(wa, request_data)
    assert first["recipient"] == "639171111111"
    assert second["recipient"] == "639172222222"
    assert first["voice_request"]["first_name"] == "Juan"
    assert second["voice_request"]["first_name"] == "Maria"
    payload = reserve(wa, second)["payload"]
    assert payload["to"] == second["recipient"]
    assert payload["audio"]["voice"] is True
    # Workflow-level Hello must never be reused for a different customer's reply window.
    request_data["row"].update(customer_id="C3", last_hello_at_utc="")
    assert claim(wa, request_data)["reason"] == "reply_window_required"
    request_data["row"].update(phone="09171234567")
    assert claim(wa, request_data)["reason"] == "invalid_phone"


def test_customer_routing_can_be_disabled_after_claim(wa, request_data):
    wa.settings.whatsapp_customer_routing_enabled = True
    request_data["routing_mode"] = "customer"
    result = claim(wa, request_data)
    wa.settings.whatsapp_customer_routing_enabled = False
    with pytest.raises(RoutingBlocked):
        reserve(wa, result)


def test_reservation_cannot_change_recipient_or_replay(wa, request_data):
    result = claim(wa, request_data)
    with pytest.raises(StateConflict):
        reserve(wa, result, recipient="639172222222")
    assert reserve(wa, result)["proceed"]
    with pytest.raises(StateConflict):
        reserve(wa, result)
    assert not claim(wa, request_data)["proceed"]  # Includes crash before acknowledgement.


@pytest.mark.parametrize("stage", ["tts_failed", "upload_failed"])
def test_safe_failure_backoff_limits_and_stale_tokens(wa, request_data, stage):
    wa.settings.max_attempts = 2
    wa.settings.retry_delay_seconds = 300
    first = claim(wa, request_data)
    outcome(wa, first, "failed", stage)
    outcome(wa, first, "failed", stage)  # Lost acknowledgement can be replayed safely.
    assert claim(wa, request_data)["reason"] == "retry_backoff"
    with wa.connect() as conn:
        conn.execute(
            "UPDATE whatsapp_reminders SET retry_after=now()-interval '1 second' "
            "WHERE reminder_id=%s",
            (first["reminder_id"],),
        )
    second = claim(wa, request_data)
    assert second["token"] != first["token"]
    with pytest.raises(StateConflict):
        outcome(wa, first, "failed", stage)
    outcome(wa, second, "failed", stage)
    assert claim(wa, request_data)["reason"] == "retry_limit"


def test_processing_crash_recovery(wa, request_data):
    first = claim(wa, request_data)
    with wa.connect() as conn:
        conn.execute(
            "UPDATE whatsapp_reminders SET lease_until=now()-interval '1 second' "
            "WHERE reminder_id=%s",
            (first["reminder_id"],),
        )
    with pytest.raises(StateConflict):
        reserve(wa, first)
    second = claim(wa, request_data)
    assert second["proceed"]
    with pytest.raises(StateConflict):
        reserve(wa, first)


def test_window_expired_during_preparation(wa, request_data):
    first = claim(wa, request_data)
    with wa.connect() as conn:
        conn.execute(
            "UPDATE whatsapp_reminders SET window_expires_at=now() WHERE reminder_id=%s",
            (first["reminder_id"],),
        )
    assert reserve(wa, first) == {"proceed": False, "status": "failed", "reason": "window_expired"}
    assert wa.history(1)[0]["error_message"] == "window_expired"


@pytest.mark.parametrize(
    "status,error",
    [
        ("unknown", "submission_uncertain"),
        ("rejected", "provider_rejected"),
    ],
)
def test_uncertain_and_rejected_sends_never_auto_retry(wa, request_data, status, error):
    first = claim(wa, request_data)
    reserve(wa, first)
    outcome(wa, first, status, error)
    assert not claim(wa, request_data)["proceed"]
    with pytest.raises(StateConflict):
        outcome(wa, first, "failed", "tts_failed")


def test_explicit_rate_limit_can_retry_later(wa, request_data):
    first = claim(wa, request_data)
    reserve(wa, first)
    outcome(wa, first, "failed", "provider_rate_limited")
    assert claim(wa, request_data)["proceed"]


def test_identity_is_independent_of_spoken_names_and_recipient(wa, request_data):
    first = claim(wa, request_data)
    reserve(wa, first)
    outcome(wa, first, "submitted", message="wamid.test")
    request_data["row"].update(agent_name="Other Agent", bank_name="Other Spoken Bank")
    wa.settings.whatsapp_test_recipient = "639172222222"
    request_data["test_recipient"] = "639172222222"
    assert not claim(wa, request_data)["proceed"]
    request_data["row"]["due_date"] = "2026-12-15"
    assert claim(wa, request_data)["proceed"]


def test_http_roundtrip_and_private_history(wa, request_data):
    headers = {"X-API-Key": wa.settings.reminder_api_key.get_secret_value()}
    with TestClient(create_app(wa.settings, whatsapp_store=wa)) as api:
        base = "/api/v1/whatsapp/reminders"
        first = api.post(base + "/claim", json=request_data, headers=headers).json()
        wa.test_ids.add(first["reminder_id"])
        url = base + "/" + first["reminder_id"]
        body = {"token": first["token"], "recipient": first["recipient"], "media_id": "12345"}
        assert api.post(url + "/reserve", json=body, headers=headers).status_code == 200
        assert api.post(url + "/reserve", json=body, headers=headers).status_code == 409
        body = {"token": first["token"], "status": "submitted", "message_id": "wamid.test"}
        assert api.post(url + "/outcome", json=body, headers=headers).status_code == 200
        history = api.get(base, headers=headers).json()
        encoded = json.dumps(history)
        for secret in [first["token"], first["recipient"], "Juan", "juan@example.com"]:
            assert secret not in encoded
        assert history[0]["status"] == "submitted"
