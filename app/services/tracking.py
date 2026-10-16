import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from pydantic import ValidationError

from app.core.config import Settings
from app.models import Customer, TransitionRequest
from app.services.templates import Templates


class StateConflict(Exception):
    pass


class TrackingStore:
    """Short PostgreSQL transactions; no transaction is held during TTS or SMTP."""

    def __init__(self, settings: Settings, templates: Templates):
        self.settings = settings
        self.templates = templates

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(
            self.settings.database_url.get_secret_value(),
            row_factory=dict_row,
            connect_timeout=5,
            options="-c statement_timeout=5000",
        )

    def initialize(self) -> None:
        with self.connect() as conn:
            # Serialize concurrent startup migrations across API instances.
            conn.execute("SELECT pg_advisory_xact_lock(7162451)")
            conn.execute(Path(__file__).resolve().parents[1].joinpath("schema.sql").read_text())

    @staticmethod
    def event(
        conn: psycopg.Connection, reminder_id: str, status: str, reason: str | None = None
    ) -> None:
        conn.execute(
            "INSERT INTO reminder_events(reminder_id,status,reason) VALUES (%s,%s,%s)",
            (reminder_id, status, reason),
        )

    def claim(self, raw: dict[str, Any]) -> dict[str, Any]:
        mode = "dry_run" if self.settings.dry_run else "test_email"
        customer = None
        reason = None
        try:
            customer = Customer.model_validate(raw)
            if not customer.reminder_eligible:
                reason = "ineligible"
        except ValidationError:
            reason = "invalid_record"
        if customer is not None:
            # One reminder per institution/customer/due date/channel/mode. Changes
            # to templates, recipient overrides or voices do not bypass deduplication.
            identity = [
                self.settings.tenant_id,
                customer.bank_name.casefold(),
                customer.customer_id,
                str(customer.due_date),
                "email",
                mode,
            ]
        else:
            identity = [self.settings.tenant_id, "invalid", raw, mode]
        reminder_id = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO reminders(reminder_id,customer_id,due_date,mode,status)
                   VALUES (%s,%s,%s,%s,'pending') ON CONFLICT DO NOTHING""",
                (
                    reminder_id,
                    customer.customer_id if customer else None,
                    customer.due_date if customer else None,
                    mode,
                ),
            )
            row = conn.execute(
                """SELECT *, lease_until > now() AS leased, retry_after > now() AS cooling
                   FROM reminders WHERE reminder_id=%s FOR UPDATE""",
                (reminder_id,),
            ).fetchone()
            terminal = row["status"] in {"sent", "submitting", "unknown", "dry_run"}
            if terminal or (row["status"] == "processing" and row["leased"]):
                self.event(conn, reminder_id, "skipped", "duplicate_or_in_progress")
                return {
                    "proceed": False,
                    "reminder_id": reminder_id,
                    "reason": "duplicate_or_in_progress",
                }
            if reason:
                conn.execute(
                    """UPDATE reminders SET status='skipped',error_message=%s,updated_at=now()
                       WHERE reminder_id=%s""",
                    (reason, reminder_id),
                )
                self.event(conn, reminder_id, "skipped", reason)
                return {"proceed": False, "reminder_id": reminder_id, "reason": reason}
            if row["attempt_count"] >= self.settings.max_attempts or row["cooling"]:
                self.event(conn, reminder_id, "skipped", "retry_limit_or_backoff")
                return {
                    "proceed": False,
                    "reminder_id": reminder_id,
                    "reason": "retry_limit_or_backoff",
                }
            token = uuid4()
            conn.execute(
                """UPDATE reminders SET status='processing',token=%s,
                   lease_until=now() + make_interval(secs => %s),retry_after=NULL,
                   attempt_count=attempt_count+1,error_message=NULL,updated_at=now()
                   WHERE reminder_id=%s""",
                (token, self.settings.lease_seconds, reminder_id),
            )
            self.event(conn, reminder_id, "processing")
        request = customer.voice_request()
        return {
            "proceed": True,
            "reminder_id": reminder_id,
            "token": str(token),
            "dry_run": self.settings.dry_run,
            "recipient": self.settings.test_recipient,
            "sender": self.settings.sender_email,
            "voice_request": request.model_dump(mode="json", exclude_none=True),
            "script": self.templates.render("voice", request),
            "subject": self.templates.render("subject", request),
            "body": self.templates.render("email", request),
        }

    def transition(self, reminder_id: str, request: TransitionRequest) -> dict[str, str]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT *,lease_until > now() AS leased FROM reminders "
                "WHERE reminder_id=%s FOR UPDATE",
                (reminder_id,),
            ).fetchone()
            if not row or row["token"] != request.token:
                raise StateConflict
            # Only terminal acknowledgements are replayable. Replaying 'submitting'
            # must fail, otherwise resuming the send node could send a second email.
            if row["status"] == request.status and request.status in {
                "sent",
                "failed",
                "unknown",
                "dry_run",
            }:
                return {"status": request.status}
            allowed = {
                "processing": {"failed", "dry_run"}
                if row["mode"] == "dry_run"
                else {"failed", "submitting"},
                "submitting": {"sent", "unknown"},
            }
            if request.status not in allowed.get(row["status"], set()):
                raise StateConflict
            if row["status"] == "processing" and not row["leased"]:
                raise StateConflict
            if request.status == "failed" and request.error_code not in {
                "tts_failed",
                "preview_failed",
            }:
                raise StateConflict
            if request.status == "unknown" and request.error_code != "smtp_uncertain":
                raise StateConflict
            conn.execute(
                """UPDATE reminders SET status=%s,error_message=%s,updated_at=now(),
                   sent_at=CASE WHEN %s='sent' THEN now() ELSE sent_at END,
                   retry_after=CASE WHEN %s='failed'
                       THEN now() + make_interval(secs => %s) ELSE NULL END
                   WHERE reminder_id=%s""",
                (
                    request.status,
                    request.error_code,
                    request.status,
                    request.status,
                    self.settings.retry_delay_seconds,
                    reminder_id,
                ),
            )
            self.event(conn, reminder_id, request.status, request.error_code)
        return {"status": request.status}

    def history(self, limit: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return conn.execute(
                """SELECT reminder_id,customer_id,due_date,channel,mode,status,attempt_count,
                   sent_at,error_message,created_at,updated_at FROM reminders
                   ORDER BY updated_at DESC LIMIT %s""",
                (limit,),
            ).fetchall()
