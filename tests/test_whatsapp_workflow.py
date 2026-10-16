import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.build_whatsapp_workflow import CONFIG, build_workflow

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 16, 4, 0, tzinfo=timezone.utc)


def execute_code(name, data, config=None, now=NOW):
    payload = {
        "script": str(ROOT / "workflows/code" / name),
        "json": data,
        "config": config,
        "now": int(now.timestamp() * 1000),
    }
    response = subprocess.run(
        ["node", str(ROOT / "tests/whatsapp_code_runner.js")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(response.stdout)


@pytest.fixture
def live_config():
    return {
        **CONFIG,
        "mode": "send",
        "test_recipient": "+639171234567",
        "phone_number_id": "123456789012345",
        "graph_api_version": "v23.0",
        "last_hello_at_utc": "2026-10-16T03:59:00Z",
        "meta_test_number_confirmed": True,
        "recipient_verified": True,
    }


def test_preview_without_meta_account():
    result = execute_code("whatsapp_validate.js", CONFIG)["result"]["json"]
    assert result["mode"] == "preview"
    assert result["test_recipient"] == ""
    assert "fictional" in result["voice_request"]["bank_name"]


def test_verified_recipient_and_fictional_voice(live_config):
    result = execute_code("whatsapp_validate.js", live_config)["result"]["json"]
    assert result["test_recipient"] == "639171234567"
    assert result["voice_request"]["first_name"] == "Alex"
    assert result["voice_request"]["customer_id"] == "WHATSAPP-DEMO"


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "production"),
        ("mode", True),
        ("first_name", "<speak>Hi</speak>"),
        ("test_recipient", "09171234567"),
        ("test_recipient", "639171234567,639172222222"),
        ("test_recipient", "63917 1234567"),
        ("phone_number_id", "12345/../messages"),
        ("phone_number_id", 12345),
        ("graph_api_version", "https://other.example"),
        ("graph_api_version", ""),
        ("recipient_verified", "true"),
        ("meta_test_number_confirmed", False),
        ("last_hello_at_utc", ""),
        ("last_hello_at_utc", "2026-10-16T05:00:00Z"),
        ("last_hello_at_utc", "2026-10-15T04:00:00Z"),
        ("last_hello_at_utc", "2026-10-15T04:01:00Z"),
    ],
)
def test_invalid_setup_blocks_before_tts(live_config, field, value):
    live_config[field] = value
    assert "error" in execute_code("whatsapp_validate.js", live_config)


def test_window_rechecked_after_upload(live_config):
    config = execute_code("whatsapp_validate.js", live_config)["result"]["json"]
    prepared = execute_code("whatsapp_before_send.js", {"id": "12345"}, config)["result"]["json"]
    assert prepared == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "639171234567",
        "type": "audio",
        "audio": {"id": "12345"},
    }
    assert "error" in execute_code(
        "whatsapp_before_send.js", {"id": "12345"}, config, NOW + timedelta(hours=24)
    )
    assert "error" in execute_code("whatsapp_before_send.js", {"id": "bad/id"}, config)


@pytest.mark.parametrize(
    "response,expected",
    [
        ({"messages": [{"id": "wamid.example"}]}, "submitted"),
        ({"error": {"message": "private provider details"}}, "unknown"),
        ({}, "unknown"),
        ({"messages": [{"id": "not-a-message"}]}, "unknown"),
    ],
)
def test_outcome_does_not_claim_delivery_or_retry(response, expected):
    result = execute_code("whatsapp_result.js", response)["result"]["json"]
    assert result["status"] == expected
    assert result["automatic_retry"] is False
    assert "private provider details" not in json.dumps(result)


def test_export_reproducible_and_independent():
    workflow = build_workflow()
    assert workflow == json.loads((ROOT / "workflows/whatsapp_voice_test.json").read_text())
    assert workflow["id"] != "voiceReminderMvp"
    assert not workflow["active"] and not workflow["pinData"]
    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert nodes["Demo Settings"]["parameters"]["mode"] == "raw"
    assert json.loads(nodes["Demo Settings"]["parameters"]["jsonOutput"]) == CONFIG
    assert nodes["Send WhatsApp Audio"]["retryOnFail"] is False
    assert nodes["Upload MP3 to Meta"]["parameters"]["bodyParameters"]["parameters"][-1] == {
        "parameterType": "formBinaryData",
        "name": "file",
        "inputDataFieldName": "audio",
    }
    for node in nodes.values():
        assert "credentials" not in node
        assert node["type"] not in {"n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.emailSend"}
    assert "https://graph.facebook.com/" in nodes["Send WhatsApp Audio"]["parameters"]["url"]
    original = json.loads((ROOT / "workflows/payment_reminder.json").read_text())
    assert original["name"] == "Fictional Voice Payment Reminders"
