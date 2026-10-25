"""Authenticated Meta notifications; short transactions, no outbound requests."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.whatsapp import WhatsAppStore, normalize_phone

MESSAGE_ID = re.compile(r"^wamid\.[A-Za-z0-9_=+./:-]{1,500}$")


def event_time(value: Any) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,12}", value):
        raise ValueError("Invalid event timestamp")
    try:
        timestamp = datetime.fromtimestamp(int(value), timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise ValueError("Invalid event timestamp") from None
    if timestamp > datetime.now(timezone.utc) + timedelta(seconds=60):
        raise ValueError("Future event timestamp")
    return timestamp


class WebhookStore(WhatsAppStore):
    def ingest(self, payload: dict) -> dict[str, int]:
        counts = {"incoming": 0, "statuses": 0, "ignored": 0}
        if payload.get("object") != "whatsapp_business_account":
            return counts
        # A single transaction commits before the HTTP acknowledgement. Meta can
        # retry database failures; unique keys make retries harmless.
        with self.connect() as conn:
            for entry in payload.get("entry", []):
                if not isinstance(entry, dict):
                    raise ValueError("Invalid entry")
                if entry.get("id") != self.settings.whatsapp_business_account_id:
                    counts["ignored"] += 1
                    continue
                for change in entry.get("changes", []):
                    if not isinstance(change, dict):
                        raise ValueError("Invalid change")
                    value = change.get("value", {})
                    if not isinstance(value, dict):
                        raise ValueError("Invalid value")
                    metadata = value.get("metadata", {})
                    if not isinstance(metadata, dict):
                        raise ValueError("Invalid metadata")
                    if (
                        change.get("field") != "messages"
                        or value.get("messaging_product") != "whatsapp"
                        or metadata.get("phone_number_id") != self.settings.whatsapp_phone_number_id
                    ):
                        counts["ignored"] += 1
                        continue
                    for message in value.get("messages", []):
                        if not isinstance(message, dict):
                            raise ValueError("Invalid message")
                        # System/unsupported notifications do not open a service window.
                        if message.get("type") not in {
                            "text",
                            "audio",
                            "image",
                            "video",
                            "document",
                            "sticker",
                            "location",
                            "contacts",
                            "interactive",
                            "button",
                            "order",
                        }:
                            counts["ignored"] += 1
                            continue
                        identity, fingerprint, timestamp = self._fields(message, "from")
                        inserted = conn.execute(
                            """INSERT INTO whatsapp_inbound_events
                               (tenant_id,phone_number_id,message_id,recipient_fingerprint,occurred_at)
                               VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                               RETURNING message_id""",
                            (
                                self.settings.tenant_id,
                                self.settings.whatsapp_phone_number_id,
                                identity,
                                fingerprint,
                                timestamp,
                            ),
                        ).fetchone()
                        counts["incoming"] += bool(inserted)
                    for status in value.get("statuses", []):
                        if not isinstance(status, dict):
                            raise ValueError("Invalid status")
                        if status.get("status") not in {"sent", "delivered", "read", "failed"}:
                            counts["ignored"] += 1
                            continue
                        identity, fingerprint, timestamp = self._fields(status, "recipient_id")
                        errors = status.get("errors") or []
                        code = (
                            errors[0].get("code")
                            if errors and isinstance(errors[0], dict)
                            else None
                        )
                        if type(code) is not int or not 0 <= code <= 2147483647:
                            code = None
                        inserted = conn.execute(
                            """INSERT INTO whatsapp_delivery_events
                               (tenant_id,phone_number_id,message_id,recipient_fingerprint,
                                status,occurred_at,error_code)
                               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                               RETURNING message_id""",
                            (
                                self.settings.tenant_id,
                                self.settings.whatsapp_phone_number_id,
                                identity,
                                fingerprint,
                                status["status"],
                                timestamp,
                                code,
                            ),
                        ).fetchone()
                        counts["statuses"] += bool(inserted)
        return counts

    def _fields(self, event: dict, recipient_field: str) -> tuple[str, str, datetime]:
        identity = event.get("id", "")
        if not isinstance(identity, str) or not MESSAGE_ID.fullmatch(identity):
            raise ValueError("Invalid message identity")
        return (
            identity,
            self.fingerprint(normalize_phone(event.get(recipient_field))),
            event_time(event.get("timestamp")),
        )
