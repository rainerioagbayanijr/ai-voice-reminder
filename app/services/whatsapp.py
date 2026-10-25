"""Durable outbound WhatsApp state. Provider I/O stays in n8n, outside transactions."""

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.models import (
    Customer,
    WhatsAppClaimRequest,
    WhatsAppOutcomeRequest,
    WhatsAppReserveRequest,
)
from app.services.tracking import StateConflict, TrackingStore


class RoutingBlocked(Exception):
    pass


def normalize_phone(value: str) -> str:
    """Require an explicit international number; never guess a country code."""
    if not isinstance(value, str):
        raise ValueError("International phone required")
    value = value.strip().removeprefix("+")
    if not re.fullmatch(r"[1-9][0-9]{7,14}", value):
        raise ValueError("International phone required")
    return value


def reply_window(value: str) -> datetime:
    # Manual compatibility mode only. Webhook mode obtains timestamps from PostgreSQL.
    try:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        expiry = timestamp + timedelta(hours=24)
        if timestamp > now or expiry <= now + timedelta(minutes=2):
            raise ValueError
        return expiry
    except (ValueError, TypeError, OverflowError):
        raise ValueError("A recent incoming-message UTC timestamp is required") from None


def prepare_whatsapp_batch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    seen = set()
    for index, raw in enumerate(rows):
        item: dict[str, Any] = {"row_index": index + 1}
        try:
            customer = Customer.model_validate(
                {k: v for k, v in raw.items() if k != "last_hello_at_utc"}
            )
        except ValidationError:
            results.append({**item, "status": "skipped", "reason": "invalid_customer"})
            continue
        item["customer_id"] = customer.customer_id
        key = (customer.customer_id, customer.due_date)
        reason = (
            "ineligible"
            if not customer.reminder_eligible
            else ("duplicate_in_batch" if key in seen else None)
        )
        if reason:
            results.append({**item, "status": "skipped", "reason": reason})
            continue
        seen.add(key)
        # Do not transport email; phone is needed only by the routing/claim component.
        row = customer.model_dump(mode="json", exclude={"email"})
        row["last_hello_at_utc"] = raw.get("last_hello_at_utc", "")
        results.append(
            {
                **item,
                "status": "eligible",
                "row": row,
                "voice_request": customer.voice_request().model_dump(mode="json"),
            }
        )
    return results


class WhatsAppStore(TrackingStore):
    def fingerprint(self, recipient: str) -> str:
        return hmac.new(
            self.settings.reminder_api_key.get_secret_value().encode(),
            recipient.encode(),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def event(conn, reminder_id, status, reason=None):
        conn.execute(
            "INSERT INTO whatsapp_events(reminder_id,status,reason) VALUES (%s,%s,%s)",
            (reminder_id, status, reason),
        )

    def claim(self, request: WhatsAppClaimRequest) -> dict[str, Any]:
        if (
            request.routing_mode == "customer"
            and not self.settings.whatsapp_customer_routing_enabled
        ):
            raise RoutingBlocked("Customer routing is disabled on the backend")
        try:
            # The prepare endpoint deliberately strips email. It has no delivery role here.
            raw = {k: v for k, v in request.row.items() if k != "last_hello_at_utc"}
            raw.setdefault("email", "unused@example.com")
            customer = Customer.model_validate(raw)
        except ValidationError:
            return {"proceed": False, "status": "skipped", "reason": "invalid_customer"}
        if not customer.reminder_eligible:
            return {"proceed": False, "status": "skipped", "reason": "ineligible"}
        if request.routing_mode == "test":
            if not self.settings.whatsapp_test_recipient_verified:
                raise RoutingBlocked("Verify the backend test recipient before sending")
            try:
                recipient = normalize_phone(self.settings.whatsapp_test_recipient)
                if recipient != normalize_phone(request.test_recipient):
                    raise RoutingBlocked("Workflow and backend test recipients must match")
            except ValueError:
                raise RoutingBlocked("Configure a valid backend test recipient") from None
            window_value = request.last_hello_at_utc
        else:
            try:
                recipient = normalize_phone(customer.phone)
            except ValueError:
                return {"proceed": False, "status": "skipped", "reason": "invalid_phone"}
            window_value = request.row.get("last_hello_at_utc", "")
        try:
            if self.settings.whatsapp_window_source == "webhook":
                if request.phone_number_id != self.settings.whatsapp_phone_number_id:
                    raise RoutingBlocked("Workflow and webhook sender IDs must match")
                with self.connect() as conn:
                    incoming = conn.execute(
                        """SELECT max(occurred_at) AS last_incoming FROM whatsapp_inbound_events
                           WHERE tenant_id=%s AND phone_number_id=%s
                             AND recipient_fingerprint=%s""",
                        (
                            self.settings.tenant_id,
                            request.phone_number_id,
                            self.fingerprint(recipient),
                        ),
                    ).fetchone()["last_incoming"]
                window_value = incoming.isoformat().replace("+00:00", "Z") if incoming else ""
            expiry = reply_window(window_value)
        except ValueError:
            return {"proceed": False, "status": "skipped", "reason": "reply_window_required"}
        identity = [
            self.settings.tenant_id,
            request.institution_id,
            customer.customer_id,
            str(customer.due_date),
            "whatsapp",
            request.routing_mode,
        ]
        reminder_id = hashlib.sha256(
            json.dumps(identity, separators=(",", ":")).encode()
        ).hexdigest()
        token = uuid4()
        with self.connect() as conn:
            # ON CONFLICT + row lock serializes competing claims without holding a TTS transaction.
            inserted = conn.execute(
                """INSERT INTO whatsapp_reminders
                   (reminder_id,customer_id,institution_id,due_date,routing_mode,status,
                    token,recipient_fingerprint,phone_number_id,window_expires_at)
                   VALUES (%s,%s,%s,%s,%s,'processing',%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING RETURNING reminder_id""",
                (
                    reminder_id,
                    customer.customer_id,
                    request.institution_id,
                    customer.due_date,
                    request.routing_mode,
                    token,
                    self.fingerprint(recipient),
                    request.phone_number_id,
                    expiry,
                ),
            ).fetchone()
            row = conn.execute(
                """SELECT *,lease_until > now() AS leased,retry_after > now() AS cooling
                   FROM whatsapp_reminders WHERE reminder_id=%s FOR UPDATE""",
                (reminder_id,),
            ).fetchone()
            reason = None
            if row["status"] in {"submitting", "submitted", "unknown", "rejected"}:
                reason = "duplicate_or_review_required"
            elif not inserted and row["status"] == "processing" and row["leased"]:
                reason = "in_progress"
            elif row["attempt_count"] >= self.settings.max_attempts:
                reason = "retry_limit"
            elif row["cooling"]:
                reason = "retry_backoff"
            if reason:
                self.event(conn, reminder_id, "skipped", reason)
                return {
                    "proceed": False,
                    "status": "skipped",
                    "reminder_id": reminder_id,
                    "reason": reason,
                }
            conn.execute(
                """UPDATE whatsapp_reminders SET status='processing',token=%s,
                   lease_until=now()+make_interval(secs => %s),retry_after=NULL,
                   attempt_count=attempt_count+1,error_message=NULL,recipient_fingerprint=%s,
                   phone_number_id=%s,window_expires_at=%s,updated_at=now()
                   WHERE reminder_id=%s""",
                (
                    token,
                    self.settings.lease_seconds,
                    self.fingerprint(recipient),
                    request.phone_number_id,
                    expiry,
                    reminder_id,
                ),
            )
            self.event(conn, reminder_id, "processing")
        return {
            "proceed": True,
            "reminder_id": reminder_id,
            "token": str(token),
            "recipient": recipient,
            "routing_mode": request.routing_mode,
            "voice_request": customer.voice_request().model_dump(mode="json"),
        }

    def reserve(self, reminder_id: str, request: WhatsAppReserveRequest) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT *,lease_until > now() AS leased,
                   window_expires_at > now()+interval '30 seconds' AS window_open
                   FROM whatsapp_reminders WHERE reminder_id=%s FOR UPDATE""",
                (reminder_id,),
            ).fetchone()
            if (
                not row
                or row["token"] != request.token
                or row["status"] != "processing"
                or not row["leased"]
            ):
                raise StateConflict
            if (
                row["routing_mode"] == "customer"
                and not self.settings.whatsapp_customer_routing_enabled
            ):
                raise RoutingBlocked("Customer routing is disabled on the backend")
            if row["recipient_fingerprint"] != self.fingerprint(request.recipient):
                raise StateConflict
            if row["routing_mode"] == "test":
                if (
                    not self.settings.whatsapp_test_recipient_verified
                    or normalize_phone(self.settings.whatsapp_test_recipient) != request.recipient
                ):
                    raise RoutingBlocked("Backend test recipient changed; claim again")
            if not row["window_open"]:
                self._failure(conn, reminder_id, "failed", "window_expired")
                return {"proceed": False, "status": "failed", "reason": "window_expired"}
            conn.execute(
                "UPDATE whatsapp_reminders SET status='submitting',updated_at=now() "
                "WHERE reminder_id=%s",
                (reminder_id,),
            )
            self.event(conn, reminder_id, "submitting")
        # This permission is issued once. A lost response is deliberately not replayable.
        return {
            "proceed": True,
            "phone_number_id": row["phone_number_id"],
            "payload": {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": request.recipient,
                "type": "audio",
                "audio": {"id": request.media_id, "voice": True},
            },
        }

    def _failure(self, conn, reminder_id, status, error):
        conn.execute(
            """UPDATE whatsapp_reminders SET status=%s,error_message=%s,updated_at=now(),
               retry_after=CASE WHEN %s='failed'
               THEN now()+make_interval(secs => %s) ELSE NULL END WHERE reminder_id=%s""",
            (status, error, status, self.settings.retry_delay_seconds, reminder_id),
        )
        self.event(conn, reminder_id, status, error)

    def outcome(self, reminder_id: str, request: WhatsAppOutcomeRequest) -> dict[str, str]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT *,lease_until > now() AS leased FROM whatsapp_reminders "
                "WHERE reminder_id=%s FOR UPDATE",
                (reminder_id,),
            ).fetchone()
            if not row or row["token"] != request.token:
                raise StateConflict
            if (
                row["status"] == request.status
                and row["error_message"] == request.error_code
                and row["message_id"] == request.message_id
            ):
                return {"status": request.status}
            if row["status"] == "processing" and row["leased"]:
                valid = (
                    request.status == "failed"
                    and request.error_code
                    in {
                        "tts_failed",
                        "upload_failed",
                    }
                    and request.message_id is None
                )
            elif row["status"] == "submitting":
                valid = (
                    (
                        request.status == "submitted"
                        and request.message_id is not None
                        and request.error_code is None
                    )
                    or (
                        request.status == "unknown"
                        and request.error_code == "submission_uncertain"
                        and request.message_id is None
                    )
                    or (
                        request.status == "rejected"
                        and request.error_code == "provider_rejected"
                        and request.message_id is None
                    )
                    or (
                        request.status == "failed"
                        and request.error_code == "provider_rate_limited"
                        and request.message_id is None
                    )
                )
            else:
                valid = False
            if not valid:
                raise StateConflict
            self._failure(conn, reminder_id, request.status, request.error_code)
            if request.status == "submitted":
                conn.execute(
                    "UPDATE whatsapp_reminders SET message_id=%s,submitted_at=now() "
                    "WHERE reminder_id=%s",
                    (request.message_id, reminder_id),
                )
        return {"status": request.status}

    def history(self, limit: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return conn.execute(
                """SELECT r.reminder_id,r.customer_id,r.institution_id,r.due_date,r.routing_mode,
                   r.status,r.attempt_count,r.retry_after,r.lease_until,r.message_id,r.submitted_at,
                   r.error_message,r.created_at,r.updated_at,
                   d.status AS delivery_status,d.occurred_at AS delivery_status_at,
                   d.error_code AS delivery_error_code
                   FROM whatsapp_reminders r LEFT JOIN LATERAL (
                     SELECT status,occurred_at,error_code FROM whatsapp_delivery_events
                     WHERE tenant_id=%s AND phone_number_id=r.phone_number_id
                       AND message_id=r.message_id AND recipient_fingerprint=r.recipient_fingerprint
                     ORDER BY CASE status WHEN 'read' THEN 4 WHEN 'delivered' THEN 3
                              WHEN 'failed' THEN 2 ELSE 1 END DESC,occurred_at DESC LIMIT 1
                   ) d ON true ORDER BY r.updated_at DESC LIMIT %s""",
                (self.settings.tenant_id, limit),
            ).fetchall()
