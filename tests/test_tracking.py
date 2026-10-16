import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.main import create_app
from app.models import TransitionRequest
from app.services.templates import Templates
from app.services.tracking import StateConflict, TrackingStore

pytestmark = pytest.mark.integration


@pytest.fixture
def store(settings):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    settings.database_url = SecretStr(url)
    settings.tenant_id = "test-" + uuid4().hex
    settings.retry_delay_seconds = 0
    repository = TrackingStore(settings, Templates(settings))
    repository.initialize()
    yield repository
    # Only remove rows created by this test, never truncate a supplied database.
    with repository.connect() as conn:
        for row in repository.history(1000):
            if row["reminder_id"] in getattr(repository, "test_ids", set()):
                conn.execute(
                    "DELETE FROM reminder_events WHERE reminder_id=%s", (row["reminder_id"],)
                )
                conn.execute("DELETE FROM reminders WHERE reminder_id=%s", (row["reminder_id"],))


def claim(store, row):
    result = store.claim(row)
    if not hasattr(store, "test_ids"):
        store.test_ids = set()
    store.test_ids.add(result["reminder_id"])
    return result


def transition(store, result, status, error=None):
    return store.transition(
        result["reminder_id"],
        TransitionRequest(token=result["token"], status=status, error_code=error),
    )


def test_atomic_claim_and_duplicates(store, customer):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.claim(customer), range(8)))
    store.test_ids = {results[0]["reminder_id"]}
    assert sum(result["proceed"] for result in results) == 1
    claimed = next(result for result in results if result["proceed"])
    assert claimed["recipient"] == store.settings.test_recipient
    assert claimed["recipient"] != customer["email"]
    assert transition(store, claimed, "dry_run") == {"status": "dry_run"}
    assert not claim(store, customer)["proceed"]


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("reminder_eligible", "false", "ineligible"),
        ("email", "bad-email", "invalid_record"),
        ("first_name", "", "invalid_record"),
    ],
)
def test_skipped_history(store, customer, field, value, reason):
    customer[field] = value
    result = claim(store, customer)
    assert result["reason"] == reason
    row = next(r for r in store.history(1000) if r["reminder_id"] == result["reminder_id"])
    assert row["status"] == "skipped"
    assert row["attempt_count"] == 0


def test_failed_tts_retry_and_limit(store, customer):
    store.settings.max_attempts = 2
    first = claim(store, customer)
    transition(store, first, "failed", "tts_failed")
    second = claim(store, customer)
    assert second["proceed"] and second["token"] != first["token"]
    with pytest.raises(StateConflict):
        transition(store, first, "dry_run")
    transition(store, second, "failed", "tts_failed")
    assert claim(store, customer)["reason"] == "retry_limit_or_backoff"


def test_retry_backoff(store, customer):
    store.settings.retry_delay_seconds = 300
    result = claim(store, customer)
    transition(store, result, "failed", "tts_failed")
    assert claim(store, customer)["reason"] == "retry_limit_or_backoff"


def test_lease_recovery_and_stale_worker(store, customer):
    first = claim(store, customer)
    with store.connect() as conn:
        conn.execute(
            "UPDATE reminders SET lease_until=now()-interval '1 second' WHERE reminder_id=%s",
            (first["reminder_id"],),
        )
    with pytest.raises(StateConflict):
        transition(store, first, "dry_run")
    recovered = claim(store, customer)
    assert recovered["proceed"]
    assert UUID(recovered["token"]) != UUID(first["token"])
    with pytest.raises(StateConflict):
        transition(store, first, "failed", "tts_failed")
    transition(store, recovered, "dry_run")


def test_email_uncertainty_never_auto_retries(store, customer):
    store.settings.dry_run = False
    result = claim(store, customer)
    transition(store, result, "submitting")
    with pytest.raises(StateConflict):
        transition(store, result, "submitting")
    # Crash or lost SMTP acknowledgement: submitting is already duplicate protected.
    assert not claim(store, customer)["proceed"]
    transition(store, result, "unknown", "smtp_uncertain")
    assert not claim(store, customer)["proceed"]
    with pytest.raises(StateConflict):
        transition(store, result, "failed", "tts_failed")


def test_success_and_status_ack_replay(store, customer):
    store.settings.dry_run = False
    result = claim(store, customer)
    transition(store, result, "submitting")
    transition(store, result, "sent")
    transition(store, result, "sent")
    row = next(r for r in store.history(1000) if r["reminder_id"] == result["reminder_id"])
    assert row["sent_at"] is not None
    assert row["attempt_count"] == 1
    assert not claim(store, customer)["proceed"]


def test_dryrun_does_not_suppress_email(store, customer):
    result = claim(store, customer)
    with pytest.raises(StateConflict):
        transition(store, result, "submitting")
    transition(store, result, "dry_run")
    store.settings.dry_run = False
    email = claim(store, customer)
    assert email["proceed"]
    assert email["reminder_id"] != result["reminder_id"]


def test_wrong_token_and_bypass_blocked(store, customer):
    result = claim(store, customer)
    with pytest.raises(StateConflict):
        store.transition(result["reminder_id"], TransitionRequest(token=uuid4(), status="dry_run"))
    with pytest.raises(StateConflict):
        transition(store, result, "sent")


def test_tracking_http_contract(store, customer):
    headers = {"X-API-Key": store.settings.reminder_api_key.get_secret_value()}
    with TestClient(create_app(store.settings, store=store)) as api:
        response = api.post("/api/v1/reminders/claim", json={"row": customer}, headers=headers)
        assert response.status_code == 200
        result = response.json()
        store.test_ids = {result["reminder_id"]}
        assert result["proceed"]
        url = "/api/v1/reminders/" + result["reminder_id"] + "/status"
        assert (
            api.post(
                url, json={"token": str(uuid4()), "status": "dry_run"}, headers=headers
            ).status_code
            == 409
        )
        assert (
            api.post(
                url, json={"token": result["token"], "status": "dry_run"}, headers=headers
            ).status_code
            == 200
        )
        history = api.get("/api/v1/reminders", headers=headers).json()
        assert any(r["reminder_id"] == result["reminder_id"] for r in history)
        assert all("token" not in r and "email" not in r for r in history)
