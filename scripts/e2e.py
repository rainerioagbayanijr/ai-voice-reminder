"""Exercise the actual imported n8n workflow. All SMTP stays in local capture.

Run after installing requirements-dev.txt: python scripts/e2e.py [--live]
Uses only the isolated reminder-test Compose project; leaves volumes for inspection.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "reminder-test",
    "--env-file",
    ".verification/test.env",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.test.yml",
]


def run(args, env=None):
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout[-5000:] + result.stderr[-5000:])
    return result.stdout


def execute(env):
    output = run(
        COMPOSE
        + [
            "exec",
            "-e",
            "N8N_RUNNERS_BROKER_PORT=5681",
            "n8n",
            "n8n",
            "execute",
            "--id=voiceReminderMvp",
        ],
        env,
    )
    # CLI may report node errors in a zero-exit JSON, so check execution status too.
    marker = "===================================="
    if marker not in output:
        raise RuntimeError(output[-3000:])
    result = json.loads(output.split(marker, 1)[1].strip())
    if result.get("status") != "success" or not result.get("finished"):
        raise RuntimeError(json.dumps(result.get("data", {}).get("resultData", {}))[-5000:])


def wait_ready():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if httpx.get("http://127.0.0.1:8000/ready", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError("Test API did not become ready")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Use real online Edge speech")
    args = parser.parse_args()
    run([sys.executable, "scripts/prepare_test.py"])
    env = os.environ.copy()
    env["E2E_LIVE"] = "true" if args.live else "false"
    config = dict(
        line.split("=", 1)
        for line in (ROOT / ".verification/test.env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    headers = {"X-API-Key": config["REMINDER_API_KEY"]}

    def history():
        response = httpx.get(
            "http://127.0.0.1:8000/api/v1/reminders?limit=1000", headers=headers, timeout=10
        )
        response.raise_for_status()
        return response.json()

    def captured():
        return httpx.get("http://127.0.0.1:8025/messages", timeout=5).json()

    def scenario(name, *, dry=False, fail_tts=False, smtp="accept"):
        env["E2E_TENANT_ID"] = "e2e-" + uuid4().hex
        env["E2E_TTS_FAIL"] = "true" if fail_tts else "false"
        env["DRY_RUN"] = "true" if dry else "false"
        run(COMPOSE + ["up", "-d", "--build", "--wait"], env)
        wait_ready()
        httpx.post("http://127.0.0.1:8025/reset", timeout=5).raise_for_status()
        httpx.post("http://127.0.0.1:8025/" + smtp, timeout=5).raise_for_status()
        before = {row["reminder_id"] for row in history()}
        execute(env)
        rows = [row for row in history() if row["reminder_id"] not in before]
        expected = (
            "dry_run"
            if dry
            else "failed"
            if fail_tts
            else ("sent" if smtp == "accept" else "unknown")
        )
        assert len(rows) == 4, rows
        assert sum(r["status"] == expected for r in rows) == 2, rows
        assert sum(r["status"] == "skipped" for r in rows) == 2, rows
        messages = captured()
        expected_count = 0 if dry or fail_tts or smtp == "reject" else 2
        assert len(messages) == expected_count, messages
        for message in messages:
            assert message["to"] == "capture@example.com"
            assert len(message["attachments"]) == 1
            assert message["attachments"][0]["filename"] == "payment_reminder.mp3"
        if messages:
            recordings = [base64.b64decode(m["attachments"][0]["data"]) for m in messages]
            assert recordings[0] != recordings[1]
            if args.live:
                assert all(len(audio) > 1000 for audio in recordings)
            else:
                assert recordings == [b"ID3-test-fixture-Juan", b"ID3-test-fixture-Maria"]
        if dry:
            for row in rows:
                if row["status"] == "dry_run":
                    assert (ROOT / "previews" / (row["reminder_id"] + ".mp3")).is_file()
        execute(env)
        assert len(captured()) == expected_count, "Rerun must not submit duplicates"
        print(
            f"PASS {name}: 5 CSV rows, 2 {expected}, 2 skipped, duplicates suppressed", flush=True
        )
        return rows

    # Start once and import the exact export plus the local capture credential.
    run(COMPOSE + ["up", "-d", "--build", "--wait"], env)
    run(
        COMPOSE + ["exec", "n8n", "n8n", "import:credentials", "--input=/verification/smtp.json"],
        env,
    )
    run(
        COMPOSE + ["exec", "n8n", "n8n", "import:workflow", "--input=/verification/workflow.json"],
        env,
    )
    scenario("email attachment and repeat execution")
    scenario("dry run previews", dry=True)
    # Live mode uses real speech for success/dry runs; failure injection uses fixtures.
    if not args.live:
        scenario("SMTP rejection", smtp="reject")
        scenario("SMTP lost acknowledgement", smtp="disconnect")
        rows = scenario("TTS failure", fail_tts=True)
        # Advance only test retry clocks; preserve same tenant and real tracking data.
        env["E2E_TTS_FAIL"] = "false"
        time_sql = (
            "UPDATE reminders SET retry_after=now() WHERE reminder_id IN ("
            + ",".join("'" + r["reminder_id"] + "'" for r in rows if r["status"] == "failed")
            + ")"
        )
        run(
            COMPOSE
            + ["exec", "postgres", "psql", "-U", "reminder", "-d", "reminders", "-c", time_sql],
            env,
        )
        run(COMPOSE + ["up", "-d", "--wait", "tts-service"], env)
        wait_ready()
        execute(env)
        assert len(captured()) == 2
        retried = [
            r
            for r in history()
            if r["reminder_id"] in {x["reminder_id"] for x in rows} and r["status"] == "sent"
        ]
        assert len(retried) == 2 and all(r["attempt_count"] == 2 for r in retried)
        print("PASS retry after TTS recovery: 2 submitted, attempt_count=2", flush=True)
    print("E2E complete. Local capture only; no external emails sent.", flush=True)


if __name__ == "__main__":
    main()
