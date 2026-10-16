from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    reminder_api_key: SecretStr = Field(min_length=32)
    database_url: SecretStr | None = None
    dry_run: bool = True
    test_recipient: str = "preview@example.com"
    test_recipient_verified: bool = False
    sender_email: str = "support@example.com"
    tenant_id: str = Field(default="fictional-demo", pattern=r"^[a-z0-9-]{1,50}$")
    voice: str = "en-US-JennyNeural"
    allowed_voices: str = "en-US-JennyNeural,en-US-AriaNeural"
    language: str = "en"
    rate: str = "-15%"
    volume: str = "-5%"
    template_dir: Path = Path(__file__).resolve().parents[1] / "templates"
    tts_timeout_seconds: float = Field(default=45, gt=0, le=120)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    max_audio_bytes: int = Field(default=5_000_000, ge=1024)
    lease_seconds: int = Field(default=600, ge=300, le=3600)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_delay_seconds: int = Field(default=300, ge=0, le=86400)

    @model_validator(mode="after")
    def safe_delivery_config(self):
        from app.models import safe_email

        self.test_recipient = safe_email(self.test_recipient)
        self.sender_email = safe_email(self.sender_email)
        if not self.dry_run and not self.test_recipient_verified:
            raise ValueError("Verify ownership of TEST_RECIPIENT before disabling DRY_RUN")
        if self.voice not in self.allowed_voices.split(","):
            raise ValueError("VOICE must be in ALLOWED_VOICES")
        if self.language not in {"en", "fil"}:
            raise ValueError("LANGUAGE must be en or fil; supply matching approved templates")
        return self
