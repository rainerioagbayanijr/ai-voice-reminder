import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_workflow_guards_and_binary_contract():
    workflow = json.loads((ROOT / "workflows/payment_reminder.json").read_text())
    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert not workflow["active"]
    assert nodes["Each Customer"]["parameters"]["batchSize"] == 1
    assert nodes["Send Test Email"]["retryOnFail"] is False
    assert nodes["Reserve SMTP Submission"]["retryOnFail"] is False
    assert nodes["Send Test Email"]["parameters"]["options"]["fileAttachments"] == "audio"
    assert nodes["Send Test Email"]["parameters"]["toEmail"] == "={{ $json.recipient }}"
    assert "customer.email" not in json.dumps(workflow)
    assert nodes["Generate Audio"]["parameters"]["options"]["response"]["response"] == {
        "responseFormat": "file",
        "outputPropertyName": "audio",
    }
    for connection in workflow["connections"].values():
        for output in connection["main"]:
            for edge in output:
                assert edge["node"] in nodes


def test_compose_local_binding_and_persistence():
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert set(config["services"]) == {
        "tts-service",
        "n8n",
        "postgres",
        "webhook-gateway",
        "webhook-tunnel",
    }
    for name in ("webhook-gateway", "webhook-tunnel"):
        assert config["services"][name]["profiles"] == ["webhook"]
        assert not config["services"][name].get("ports")
    assert "app.webhook_main:create_app" in config["services"]["webhook-gateway"]["command"]
    assert "http://webhook-gateway:8001" in config["services"]["webhook-tunnel"]["command"]
    assert config["services"]["n8n"]["image"].endswith(":2.43.6")
    for service in config["services"].values():
        for port in service.get("ports", []):
            assert port.startswith("127.0.0.1:")
        assert service.get("healthcheck") or (
            service.get("build") and "HEALTHCHECK" in (ROOT / "Dockerfile").read_text()
        )
    assert config["volumes"].keys() >= {"postgres_data", "n8n_data"}
