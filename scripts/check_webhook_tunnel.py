"""Exercise public ingress without sending a WhatsApp message or recording a Hello.

Run from the repository root. Secrets are read locally and never printed.
"""

import hashlib
import hmac
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402


def request(url, *, data=None, headers=None):
    try:
        with urlopen(Request(url, data=data, headers=headers or {}), timeout=20) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, b""
    except (URLError, TimeoutError):
        # Exception text may contain a verification-token query string.
        return 0, b""


def main():
    settings = Settings()
    logs = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "webhook-tunnel"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    urls = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", logs.stdout + logs.stderr)
    if not urls:
        raise SystemExit("No tunnel URL found; start the webhook profile first.")
    base = urls[-1]
    callback = base + "/webhooks/whatsapp"
    token = settings.whatsapp_webhook_verify_token
    if not token or not token.get_secret_value():
        raise SystemExit("Set WHATSAPP_WEBHOOK_VERIFY_TOKEN before testing.")
    checks = {}
    status, body = request(
        callback
        + "?"
        + urlencode(
            {
                "hub.mode": "subscribe",
                "hub.challenge": "123456789",
                "hub.verify_token": token.get_secret_value(),
            }
        )
    )
    checks["verification"] = status == 200 and body == b"123456789"
    checks["wrong_token"] = (
        request(
            callback
            + "?"
            + urlencode(
                {
                    "hub.mode": "subscribe",
                    "hub.challenge": "123",
                    "hub.verify_token": "wrong",
                }
            )
        )[0]
        == 403
    )
    for path in ["/docs", "/openapi.json", "/api/v1/whatsapp/reminders"]:
        checks[path] = request(base + path)[0] == 404
    secret = settings.whatsapp_app_secret
    ready = bool(secret and secret.get_secret_value())
    checks["invalid_signature"] = request(
        callback,
        data=b"{}",
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
        },
    )[0] == (401 if ready else 503)
    if ready:
        # An unrelated object must be acknowledged without inserting any events.
        body = b'{"object":"tunnel_connectivity_test"}'
        signature = hmac.new(secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
        checks["signed_notification"] = (
            request(
                callback,
                data=body,
                headers={
                    "X-Hub-Signature-256": "sha256=" + signature,
                },
            )[0]
            == 200
        )
    folder = ROOT / ".verification"
    folder.mkdir(exist_ok=True)
    (folder / "webhook-callback-url.txt").write_text(callback + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"callback_url": callback, "checks": checks, "app_secret_configured": ready}, indent=2
        )
    )
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
