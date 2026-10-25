import re
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    reminder_api_key: SecretStr = Field(min_length=32)
    database_url: SecretStr | None = None
    dry_run: bool = True
    test_recipient: str = "preview@example.com"
    test_recipient_verified: bool = False
    sender_email: str = "support@example.com"
    tenant_id: str = Field(default="fictional-demo", pattern=r"^[a-z0-9-]{1,50}$")
    voice: str = "en-US-JennyNeural"
    tts_provider: Literal["edge", "elevenlabs"] = "edge"
    elevenlabs_api_key: SecretStr | None = None
    elevenlabs_voice_id: str = Field(default="", pattern=r"^[A-Za-z0-9_-]{0,80}$")
    elevenlabs_allowed_voices: str = Field(default="", max_length=1000)
    elevenlabs_model_id: str = Field(default="", pattern=r"^[A-Za-z0-9_-]{0,80}$")
    elevenlabs_language_code: str = Field(default="", pattern=r"^([a-z]{2})?$")
    elevenlabs_speed: float = Field(default=0.85, ge=0.7, le=1.2)
    elevenlabs_stability: float = Field(default=0.5, ge=0, le=1)
    elevenlabs_similarity_boost: float = Field(default=0.75, ge=0, le=1)
    allowed_voices: str = "en-US-JennyNeural,en-US-AriaNeural"
    language: str = "en"
    rate: str = "-15%"
    volume: str = "-5%"
    template_dir: Path = Path(__file__).resolve().parents[1] / "templates"
    tts_timeout_seconds: float = Field(default=45, gt=0, le=120)
    audio_conversion_timeout_seconds: float = Field(default=10, gt=0, le=30)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    max_audio_bytes: int = Field(default=5_000_000, ge=1024)
    lease_seconds: int = Field(default=600, ge=300, le=3600)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_delay_seconds: int = Field(default=300, ge=0, le=86400)
    whatsapp_test_recipient: str = ""
    whatsapp_test_recipient_verified: bool = False
    whatsapp_customer_routing_enabled: bool = False
    whatsapp_window_source: Literal["manual", "webhook"] = "manual"
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_webhook_verify_token: SecretStr | None = None
    whatsapp_phone_number_id: str = Field(default="", pattern=r"^([0-9]{5,32})?$")
    whatsapp_business_account_id: str = Field(default="", pattern=r"^([0-9]{5,32})?$")

    @model_validator(mode="after")
    def safe_delivery_config(self):
        from app.models import safe_email

        self.test_recipient = safe_email(self.test_recipient)
        self.sender_email = safe_email(self.sender_email)
        if not self.dry_run and not self.test_recipient_verified:
            raise ValueError("Verify ownership of TEST_RECIPIENT before disabling DRY_RUN")
        if self.tts_provider == "edge" and self.voice not in self.allowed_voices.split(","):
            raise ValueError("VOICE must be in ALLOWED_VOICES")
        if self.tts_provider == "elevenlabs":
            if (
                not self.elevenlabs_api_key
                or not self.elevenlabs_api_key.get_secret_value().strip()
            ):
                raise ValueError("ELEVENLABS_API_KEY is required for the selected provider")
            if not self.elevenlabs_voice_id or not self.elevenlabs_model_id:
                raise ValueError("ELEVENLABS_VOICE_ID and ELEVENLABS_MODEL_ID are required")
            voices = [v.strip() for v in self.elevenlabs_allowed_voices.split(",") if v.strip()]
            if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", v) for v in voices):
                raise ValueError("ELEVENLABS_ALLOWED_VOICES contains an invalid voice ID")
            if voices and self.elevenlabs_voice_id not in voices:
                raise ValueError("Default ElevenLabs voice must be in its allowlist")
            if (
                self.elevenlabs_model_id == "eleven_multilingual_v2"
                and self.elevenlabs_language_code
            ):
                raise ValueError("The selected model does not support language_code")
        if self.elevenlabs_api_key and any(
            c in self.elevenlabs_api_key.get_secret_value() for c in "\r\n\t"
        ):
            raise ValueError("Invalid speech-provider credential")
        if self.language not in {"en", "fil"}:
            raise ValueError("LANGUAGE must be en or fil; supply matching approved templates")
        return self
