"""Create ignored local capture configuration; never real SMTP credentials."""

import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / ".verification"
folder.mkdir(exist_ok=True)
path = folder / "test.env"
if not path.exists():
    path.write_text(
        "\n".join(
            [
                "REMINDER_API_KEY=" + secrets.token_hex(32),
                "N8N_ENCRYPTION_KEY=" + secrets.token_hex(32),
                "POSTGRES_PASSWORD=" + secrets.token_hex(24),
                "DRY_RUN=false",
                "TEST_RECIPIENT=capture@example.com",
                "TEST_RECIPIENT_VERIFIED=true",
                "SENDER_EMAIL=support@example.com",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
credentials = [
    {
        "id": "localCaptureSmtp",
        "name": "Local Capture SMTP",
        "type": "smtp",
        "data": {
            "host": "smtp-sink",
            "port": 1025,
            "secure": False,
            "disableStartTls": True,
            "user": "",
            "password": "",
        },
    }
]
(folder / "smtp.json").write_text(json.dumps(credentials), encoding="utf-8")
workflow = json.loads((ROOT / "workflows/payment_reminder.json").read_text(encoding="utf-8"))
for node in workflow["nodes"]:
    if node["name"] == "Send Test Email":
        node["credentials"] = {"smtp": {"id": "localCaptureSmtp", "name": "Local Capture SMTP"}}
(folder / "workflow.json").write_text(json.dumps(workflow), encoding="utf-8")
print("Prepared ignored test.env, smtp.json, workflow.json in .verification")
