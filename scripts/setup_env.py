"""Create safe local defaults with unique secrets; never overwrite configuration."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / ".env"
if destination.exists():
    print(".env already exists; preserved. Edit it directly if configuration changes are needed.")
    raise SystemExit(0)
lines = []
for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
    name = line.split("=", 1)[0]
    if name in {"REMINDER_API_KEY", "N8N_ENCRYPTION_KEY", "POSTGRES_PASSWORD"}:
        line = name + "=" + secrets.token_hex(32)
    lines.append(line)
with destination.open("x", encoding="utf-8") as file:
    file.write("\n".join(lines) + "\n")
print("Created ignored .env with unique secrets and DRY_RUN=true. No email sending enabled.")
