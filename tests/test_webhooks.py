import hashlib
import hmac
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.models import WhatsAppClaimRequest, WhatsAppOutcomeRequest, WhatsAppReserveRequest
from app.services.templates import Templates
from app.services.webhooks import WebhookStore
from app.webhook_main import MAX_BODY, create_app

PHONE = "123456789012345"
WABA = "987654321012345"
RECIPIENT = "639171234567"


@pytest.fixture
def configured(settings):
    settings.whatsapp_app_secret = SecretStr("test-app-secret")
    settings.whatsapp_webhook_verify_token = SecretStr("test-verification-token")
    settings.whatsapp_phone_number_id = PHONE
    settings.whatsapp_business_account_id = WABA
    return settings


def payload(*, incoming=None, statuses=None):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": PHONE},
                            "messages": incoming or [],
                            "statuses": statuses or [],
                        },
                    }
                ],
            }
        ],
    }


def message(**changes):
    return {
        "id": "wamid." + uuid4().hex,
        "from": RECIPIENT,
        "type": "text",
        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        "text": {"body": "Do not retain this message"},
        **changes,
    }


def receipt(identity, status="delivered", **changes):
    return {
        "id": identity,
        "recipient_id": RECIPIENT,
        "status": status,
        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        **changes,
    }


def post(client, data, secret="test-app-secret", **changes):
    body = json.dumps(data).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": signature}, **changes
    )


class MemoryStore:
    def __init__(self):
        self.calls = []

    def ingest(self, data):
        self.calls.append(data)
        return {"incoming": 1, "statuses": 0, "ignored": 0}


def test_verification_and_public_surface(configured):
    client = TestClient(create_app(configured, store=MemoryStore()))
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "test-verification-token",
        "hub.challenge": "123456",
    }
    response = client.get("/webhooks/whatsapp", params=params)
    assert response.status_code == 200 and response.text == "123456"
    assert response.headers["cache-control"] == "no-store"
    assert (
        client.get("/webhooks/whatsapp", params={**params, "hub.verify_token": "wrong"}).status_code
        == 403
    )
    assert client.get("/webhooks/whatsapp", params={**params, "hub.mode": "bad"}).status_code == 403
    assert (
        client.get("/webhooks/whatsapp", params={**params, "hub.challenge": "<x>"}).status_code
        == 400
    )
    for path in ["/docs", "/openapi.json", "/api/v1/voice/generate", "/api/v1/whatsapp/reminders"]:
        assert client.get(path).status_code == 404


def test_signature_raw_body_and_limits(configured):
    store = MemoryStore()
    client = TestClient(create_app(configured, store=store))
    assert post(client, payload()).status_code == 200
    assert len(store.calls) == 1
    assert post(client, payload(), secret="wrong").status_code == 401
    assert client.post("/webhooks/whatsapp", json=payload()).status_code == 401
    assert client.post("/webhooks/whatsapp", content=b"x" * (MAX_BODY + 1)).status_code == 413
    body = b"not-json"
    sig = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    assert (
        client.post(
            "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": sig}
        ).status_code
        == 400
    )
    assert len(store.calls) == 1


def test_missing_config_fails_closed(settings):
    client = TestClient(create_app(settings, store=MemoryStore()))
    assert client.get("/webhooks/whatsapp").status_code == 503
    assert post(client, payload()).status_code == 503


def test_database_failure_returns_retryable_error(configured):
    class Broken(MemoryStore):
        def ingest(self, data):
            raise psycopg.OperationalError("private connection detail")

    response = post(TestClient(create_app(configured, store=Broken())), payload())
    assert response.status_code == 503
    assert "private" not in response.text


@pytest.fixture
def repository(configured):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    configured.database_url = SecretStr(url)
    configured.tenant_id = "webhook-" + uuid4().hex
    configured.whatsapp_window_source = "webhook"
    configured.whatsapp_test_recipient = RECIPIENT
    configured.whatsapp_test_recipient_verified = True
    store = WebhookStore(configured, Templates(configured))
    store.initialize()
    yield store
    with store.connect() as conn:
        for table in ["whatsapp_inbound_events", "whatsapp_delivery_events"]:
            conn.execute(f"DELETE FROM {table} WHERE tenant_id=%s", (configured.tenant_id,))
        ids = conn.execute(
            "SELECT reminder_id FROM whatsapp_reminders WHERE institution_id=%s",
            (configured.tenant_id,),
        ).fetchall()
        for row in ids:
            conn.execute("DELETE FROM whatsapp_events WHERE reminder_id=%s", (row["reminder_id"],))
            conn.execute(
                "DELETE FROM whatsapp_reminders WHERE reminder_id=%s", (row["reminder_id"],)
            )


def claim_data(repository, customer):
    return WhatsAppClaimRequest(
        row=customer,
        institution_id=repository.settings.tenant_id,
        phone_number_id=PHONE,
        test_recipient=RECIPIENT,
    )


def test_incoming_dedup_window_and_recipient_isolation(repository, customer):
    request = claim_data(repository, customer)
    assert repository.claim(request)["reason"] == "reply_window_required"
    # An operator-provided timestamp never bypasses webhook mode.
    request.last_hello_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    assert repository.claim(request)["reason"] == "reply_window_required"
    wrong = message(**{"from": "639179999999"})
    repository.ingest(payload(incoming=[wrong]))
    assert repository.claim(request)["reason"] == "reply_window_required"
    data = payload(incoming=[message()])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(repository.ingest, [data] * 4))
    assert sum(r["incoming"] for r in results) == 1
    assert repository.claim(request)["proceed"] is True
    old = message(timestamp=str(int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp())))
    repository.ingest(payload(incoming=[old]))
    request.row = {**customer, "customer_id": "ANOTHER"}
    assert repository.claim(request)["proceed"] is True
    with repository.connect() as conn:
        row = conn.execute(
            "SELECT * FROM whatsapp_inbound_events WHERE tenant_id=%s LIMIT 1",
            (repository.settings.tenant_id,),
        ).fetchone()
    assert "text" not in row and RECIPIENT not in str(row)


def test_expired_wrong_sender_and_wrong_account(repository, customer):
    old = message(timestamp=str(int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp())))
    repository.ingest(payload(incoming=[old]))
    request = claim_data(repository, customer)
    assert repository.claim(request)["reason"] == "reply_window_required"
    data = payload(incoming=[message()])
    data["entry"][0]["id"] = "111111"
    assert repository.ingest(data)["ignored"] == 1
    data["entry"][0]["id"] = WABA
    data["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "222222"
    assert repository.ingest(data)["ignored"] == 1
    assert repository.claim(request)["reason"] == "reply_window_required"


def test_receipt_before_outcome_out_of_order_and_no_resend(repository, customer):
    repository.ingest(payload(incoming=[message()]))
    request = claim_data(repository, customer)
    claimed = repository.claim(request)
    repository.reserve(
        claimed["reminder_id"],
        WhatsAppReserveRequest(token=claimed["token"], recipient=RECIPIENT, media_id="12345"),
    )
    identity = "wamid." + uuid4().hex
    data = payload(statuses=[receipt(identity, "read")])
    assert repository.ingest(data)["statuses"] == 1
    assert repository.ingest(data)["statuses"] == 0
    repository.outcome(
        claimed["reminder_id"],
        WhatsAppOutcomeRequest(token=claimed["token"], status="submitted", message_id=identity),
    )
    repository.ingest(
        payload(
            statuses=[
                receipt(identity, "delivered"),
                receipt(identity, "sent"),
                receipt(identity, "failed", errors=[{"code": 131026, "message": "private"}]),
            ]
        )
    )
    row = next(r for r in repository.history(1000) if r["reminder_id"] == claimed["reminder_id"])
    assert row["status"] == "submitted" and row["delivery_status"] == "read"
    assert repository.claim(request)["reason"] == "duplicate_or_review_required"


def test_failed_receipt_and_isolation(repository, customer):
    repository.ingest(payload(incoming=[message()]))
    claimed = repository.claim(claim_data(repository, customer))
    repository.reserve(
        claimed["reminder_id"],
        WhatsAppReserveRequest(token=claimed["token"], recipient=RECIPIENT, media_id="12345"),
    )
    identity = "wamid." + uuid4().hex
    repository.outcome(
        claimed["reminder_id"],
        WhatsAppOutcomeRequest(token=claimed["token"], status="submitted", message_id=identity),
    )
    repository.ingest(payload(statuses=[receipt(identity, "read", recipient_id="639179999999")]))
    row = next(r for r in repository.history(1000) if r["reminder_id"] == claimed["reminder_id"])
    assert row["delivery_status"] is None
    repository.ingest(payload(statuses=[receipt(identity, "failed", errors=[{"code": 131026}])]))
    row = next(r for r in repository.history(1000) if r["reminder_id"] == claimed["reminder_id"])
    assert row["delivery_status"] == "failed" and row["delivery_error_code"] == 131026
    assert row["status"] == "submitted"


@pytest.mark.parametrize(
    "changes",
    [{"timestamp": "bad"}, {"from": "local"}, {"id": "bad"}, {"timestamp": "999999999999"}],
)
def test_invalid_events_rollback(repository, changes):
    client = TestClient(create_app(repository.settings, store=repository))
    assert post(client, payload(incoming=[message(), message(**changes)])).status_code == 400
    with repository.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM whatsapp_inbound_events WHERE tenant_id=%s",
                (repository.settings.tenant_id,),
            ).fetchone()["n"]
            == 0
        )


def test_unsupported_event_does_not_open_window(repository, customer):
    repository.ingest(payload(incoming=[message(type="system")]))
    assert repository.claim(claim_data(repository, customer))["reason"] == "reply_window_required"


def test_signed_http_event_opens_private_api_claim(repository, customer):
    from app.main import create_app as create_private_app

    public = TestClient(create_app(repository.settings, store=repository))
    private = TestClient(create_private_app(repository.settings, whatsapp_store=repository))
    headers = {"X-API-Key": repository.settings.reminder_api_key.get_secret_value()}
    data = claim_data(repository, customer).model_dump(mode="json")
    before = private.post("/api/v1/whatsapp/reminders/claim", json=data, headers=headers)
    assert before.json()["reason"] == "reply_window_required"
    assert post(public, payload(incoming=[message()])).status_code == 200
    after = private.post("/api/v1/whatsapp/reminders/claim", json=data, headers=headers)
    assert after.status_code == 200 and after.json()["proceed"] is True
    # Fresh app instances use the same persisted window, without a manual timestamp.
    replacement = WebhookStore(repository.settings, Templates(repository.settings))
    data["row"]["customer_id"] = "RESTARTED"
    assert replacement.claim(WhatsAppClaimRequest.model_validate(data))["proceed"] is True


def test_workflow_webhook_window_does_not_require_manual_timestamp():
    from scripts.build_whatsapp_workflow import CONFIG
    from tests.test_whatsapp_workflow import execute_code

    config = {
        **CONFIG,
        "mode": "send",
        "window_source": "webhook",
        "test_recipient": RECIPIENT,
        "phone_number_id": PHONE,
        "graph_api_version": "v25.0",
        "meta_test_number_confirmed": True,
        "recipient_verified": True,
    }
    assert "result" in execute_code("whatsapp_validate.js", config)
