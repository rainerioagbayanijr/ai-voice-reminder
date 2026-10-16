import re
import unicodedata
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def safe_email(value: str) -> str:
    if not isinstance(value, str) or any(c in value for c in "\r\n,;<>"):
        raise ValueError("One plain email address is required")
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise ValueError("Invalid email address") from exc


def clean_text(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Text required")
    value = value.strip()
    if not value or any(unicodedata.category(c).startswith("C") or c in "<>" for c in value):
        raise ValueError("Empty text or unsafe characters")
    return value


Text = Annotated[str, BeforeValidator(clean_text), Field(max_length=100)]
Email = Annotated[str, BeforeValidator(safe_email), Field(max_length=254)]
CustomerID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Percent = Annotated[str, Field(pattern=r"^[+-]\d{1,2}%$")]


class VoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: CustomerID
    first_name: Text
    bank_name: Text
    agent_name: Text
    due_date: date
    voice: str | None = Field(default=None, max_length=80)
    rate: Percent | None = None
    volume: Percent | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def iso_date_only(cls, value: Any) -> str | date:
        if not isinstance(value, (str, date)) or (
            isinstance(value, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
        ):
            raise ValueError("Use ISO YYYY-MM-DD dates")
        return value

    @field_validator("rate", "volume")
    @classmethod
    def gentle_range(cls, value: str | None) -> str | None:
        if value is not None and not -50 <= int(value[:-1]) <= 20:
            raise ValueError("Percentage must be between -50% and +20%")
        return value


class Customer(VoiceRequest):
    email: Email
    phone: str = Field(default="", max_length=30)
    reminder_eligible: bool

    @field_validator("reminder_eligible", mode="before")
    @classmethod
    def explicit_boolean(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
        raise ValueError("Use true or false")

    def voice_request(self) -> VoiceRequest:
        return VoiceRequest.model_validate(
            self.model_dump(exclude={"email", "phone", "reminder_eligible"})
        )


class ClaimRequest(BaseModel):
    row: dict[str, Any]


class CustomerBatchRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


class TransitionRequest(BaseModel):
    token: UUID
    status: Literal["submitting", "sent", "failed", "unknown", "dry_run"]
    error_code: Literal["tts_failed", "smtp_uncertain", "preview_failed"] | None = None
