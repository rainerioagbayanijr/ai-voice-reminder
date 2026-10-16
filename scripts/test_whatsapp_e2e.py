"""Actual n8n transport tests on an isolated Docker network with NO internet route.

Requires the existing API image and n8n image (already built/pulled). No Meta
account or real credential is used. Ephemeral containers/network are cleaned up.
"""

import base64
import csv
import json
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from build_whatsapp_workflow import build_workflow

ROOT = Path(__file__).resolve().parents[1]


def run(args, *, check=True, timeout=120):
    response = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    if check and response.returncode:
        raise RuntimeError(response.stdout[-3000:] + response.stderr[-3000:])
    return response


def main():
    suffix = uuid4().hex[:10]
    network = "whatsapp-test-" + suffix
    mock = "whatsapp-mock-" + suffix
    runner = "whatsapp-runner-" + suffix
    folder = ROOT / ".verification" / network
    folder.mkdir(parents=True)
    (folder / "runner.env").write_text(
        "\n".join(
            [
                "REMINDER_API_KEY=test-only-" + "x" * 32,
                "N8N_ENCRYPTION_KEY=" + secrets.token_hex(32),
                "N8N_BLOCK_ENV_ACCESS_IN_NODE=false",
                "N8N_RESTRICT_FILE_ACCESS_TO=/home/node",
                "N8N_DIAGNOSTICS_ENABLED=false",
                "N8N_PERSONALIZATION_ENABLED=false",
                "N8N_SECURE_COOKIE=false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    credential = [
        {
            "id": "whatsappLocalHeader",
            "name": "Local mock only",
            "type": "httpHeaderAuth",
            "data": {"name": "Authorization", "value": "Bearer local-whatsapp-test-only"},
        }
    ]
    (folder / "credential.json").write_text(json.dumps(credential), encoding="utf-8")
    fixture_rows = [
        {
            "customer_id": "C1",
            "first_name": "Juan",
            "email": "juan@example.com",
            "bank_name": "Fictional Bank",
            "agent_name": "Old Agent",
            "due_date": "2026-11-15",
            "reminder_eligible": "true",
        },
        {
            "customer_id": "C2",
            "first_name": "Maria",
            "email": "maria@example.com",
            "bank_name": "Fictional Bank",
            "agent_name": "Old Agent",
            "due_date": "2026-11-18",
            "reminder_eligible": "true",
        },
    ]
    fixture_rows += [
        {**fixture_rows[0], "customer_id": "C3", "reminder_eligible": "false"},
        {**fixture_rows[0], "customer_id": "C4", "email": "invalid"},
        {**fixture_rows[0]},
    ]
    with (folder / "customers.csv").open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(fixture_rows[0]))
        writer.writeheader()
        writer.writerows(fixture_rows)
    started = []
    try:
        run(["docker", "network", "create", "--internal", network])
        run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                mock,
                "--network",
                network,
                "--mount",
                f"type=bind,source={ROOT / 'tests'},target=/tests,readonly",
                "payment-reminder-mvp-tts-service:local",
                "python",
                "/tests/whatsapp_mock_server.py",
            ]
        )
        started.append(mock)

        def mock_request(path, data=None):
            source = (
                "import json,sys,urllib.request; "
                "data=None if sys.argv[2]=='null' else sys.argv[2].encode(); "
                "r=urllib.request.Request('http://localhost:8091'+sys.argv[1],data=data,"
                "headers={'Content-Type':'application/json'}); "
                "print(urllib.request.urlopen(r,timeout=5).read().decode())"
            )
            response = run(["docker", "exec", mock, "python", "-c", source, path, json.dumps(data)])
            return json.loads(response.stdout)

        run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                runner,
                "--network",
                network,
                "--env-file",
                str(folder / "runner.env"),
                "--mount",
                f"type=bind,source={folder},target=/test,readonly",
                "docker.n8n.io/n8nio/n8n:2.43.6",
            ]
        )
        started.append(runner)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            check = run(
                [
                    "docker",
                    "exec",
                    runner,
                    "node",
                    "-e",
                    "fetch('http://localhost:5678/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
                ],
                check=False,
            )
            if check.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Ephemeral n8n did not become ready")
        run(
            ["docker", "exec", runner, "n8n", "import:credentials", "--input=/test/credential.json"]
        )
        run(["docker", "cp", str(folder / "customers.csv"), runner + ":/home/node/customers.csv"])

        def scenario(name, mode="accept", *, preview=False, expired=False, csv_mode=False):
            mock_request("/reset", {"mode": mode})
            workflow = build_workflow()
            workflow.update(id="whatsappVoiceE2e", name="Ephemeral WhatsApp transport test")
            for node in workflow["nodes"]:
                params = node["parameters"]
                if node["name"] == "Demo Settings":
                    config = json.loads(params["jsonOutput"])
                    config["input_mode"] = "csv" if csv_mode else "single"
                    if not preview:
                        config.update(
                            mode="send",
                            test_recipient="639171234567",
                            phone_number_id="123456789012345",
                            graph_api_version="v23.0",
                            last_hello_at_utc=datetime.now(timezone.utc)
                            .isoformat()
                            .replace("+00:00", "Z"),
                            meta_test_number_confirmed=True,
                            recipient_verified=True,
                        )
                    if expired:
                        config["last_hello_at_utc"] = "2020-01-01T00:00:00Z"
                    params["jsonOutput"] = json.dumps(config)
                if node["name"] == "Generate Demo MP3":
                    params["url"] = f"http://{mock}:8091/tts"
                if node["name"] == "Read WhatsApp customers.csv":
                    params["fileSelector"] = "/home/node/customers.csv"
                if node["name"] == "Validate CSV Batch":
                    params["url"] = f"http://{mock}:8091/customers/prepare"
                if node["name"] in {"Upload MP3 to Meta", "Send WhatsApp Audio"}:
                    suffix = "media" if node["name"].startswith("Upload") else "messages"
                    params["url"] = f"http://{mock}:8091/v23.0/123456789012345/{suffix}"
                    node["credentials"] = {
                        "httpHeaderAuth": {"id": "whatsappLocalHeader", "name": "Local mock only"}
                    }
                if node["name"] == "Save WhatsApp Preview":
                    params["fileName"] = (
                        "={{ '/home/node/whatsapp-' + $execution.id + '-' + "
                        "$('Prepare Voice Request').item.json.voice_request.customer_id + '.mp3' }}"
                    )
            (folder / "workflow.json").write_text(json.dumps(workflow), encoding="utf-8")
            run(["docker", "exec", runner, "n8n", "import:workflow", "--input=/test/workflow.json"])
            result = run(
                [
                    "docker",
                    "exec",
                    "-e",
                    "N8N_RUNNERS_BROKER_PORT=5681",
                    runner,
                    "n8n",
                    "execute",
                    "--id=whatsappVoiceE2e",
                ],
                check=False,
            )
            output = result.stdout
            (folder / (name.replace(" ", "-").replace("/", "-") + ".log")).write_text(
                output + result.stderr, encoding="utf-8"
            )
            marker = "===================================="
            captured = mock_request("/")
            if expired:
                assert "recorded Hello" in output or "recorded Hello" in result.stderr, output[
                    -2000:
                ]
                assert captured["tts_calls"] == 0 and not captured["messages"]
                print(f"PASS {name}: blocked before synthesis/upload/send", flush=True)
                return
            assert marker in output, output[-3000:]
            data, _ = json.JSONDecoder().raw_decode(output.split(marker, 1)[1].lstrip())
            assert data["status"] == "success", data["data"]["resultData"].get("error")
            results = data["data"]["resultData"]
            last = results["lastNodeExecuted"]
            summary = results["runData"][last][-1]["data"]["main"][0][0]["json"]
            expected = (
                "preview"
                if preview
                else (
                    "failed"
                    if mode in {"tts_fail", "upload_fail"}
                    else "unknown"
                    if mode in {"send_fail", "disconnect"}
                    else "submitted"
                )
            )
            assert summary["status"] == ("batch_complete" if csv_mode else expected), summary
            if csv_mode:
                assert summary["total"] == 5 and summary["counts"] == {expected: 2, "skipped": 3}
                assert [r["first_name"] for r in summary["results"] if r["status"] == expected] == [
                    "Juan",
                    "Maria",
                ]
                assert [r["first_name"] for r in captured["tts_requests"]] == ["Juan", "Maria"]
                assert [r["due_date"] for r in captured["tts_requests"]] == [
                    "2026-11-15",
                    "2026-11-18",
                ]
                assert all(
                    r["agent_name"] == "Rain from AMG" and r["bank_name"] == "ABC Bank"
                    for r in captured["tts_requests"]
                )
                if preview:
                    assert (
                        len({r["file"] for r in summary["results"] if r["status"] == "preview"})
                        == 2
                    )
            if preview or mode in {"tts_fail", "upload_fail"}:
                assert not captured["messages"]
            else:
                assert len(results["runData"]["Send WhatsApp Audio"]) == (2 if csv_mode else 1)
            if captured["uploads"]:
                upload = captured["uploads"][0]
                assert upload["messaging_product"] == "whatsapp"
                assert upload["type"] == "audio/mpeg"
                assert upload["mime_type"] == "audio/mpeg"
                assert upload["filename"] == "payment_reminder.mp3"
                assert base64.b64decode(upload["file"]) == b"ID3-whatsapp-transport-fixture"
            if captured["messages"]:
                assert captured["messages"] == [
                    {
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": "639171234567",
                        "type": "audio",
                        "audio": {"id": "123456789"},
                    }
                ] * (2 if csv_mode else 1)
            if mode == "tts_fail":
                assert captured["tts_calls"] == 3 and not captured["uploads"]
            print(f"PASS {name}: {expected}", flush=True)

        scenario("preview without Meta", preview=True)
        scenario("multipart MP3 upload and audio send")
        scenario("upload rejection never sends", "upload_fail")
        scenario("send failure is not automatically retried", "send_fail")
        scenario("lost acknowledgement is unknown, one submission", "disconnect")
        scenario("TTS failure never uploads/sends", "tts_fail")
        scenario("expired reply window", expired=True)
        scenario("CSV preview has distinct names and filenames", preview=True, csv_mode=True)
        scenario("CSV batch routes two audio messages to test phone", csv_mode=True)
        print(
            "9 n8n scenarios passed. Local mock only; Docker test network had no internet route.",
            flush=True,
        )
    finally:
        for name in reversed(started):
            run(["docker", "stop", "--time", "3", name], check=False, timeout=20)
        run(["docker", "network", "rm", network], check=False)


if __name__ == "__main__":
    main()
