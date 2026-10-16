# API contract

Base URL: `http://localhost:8000`; inside Docker: `http://tts-service:8000`. JSON except for generated audio. All `/api/v1/*` routes require `X-API-Key`, a constant-time comparison against a 32+ character configured secret. TLS is needed beyond this local/private deployment.

## Speech

`POST /api/v1/voice/generate`

```json
{
  "customer_id": "CUST001",
  "first_name": "Juan",
  "bank_name": "Example Fictional Bank",
  "agent_name": "Alex",
  "due_date": "2026-11-15",
  "voice": "en-US-JennyNeural",
  "rate": "-15%",
  "volume": "-5%"
}
```

Voice/rate/volume are optional; remaining fields are required. Customer IDs allow letters, numbers, `_` and `-`, up to 64 characters. Names are nonempty plain text, at most 100 characters, with control characters and angle brackets rejected. Unknown fields are rejected. Dates use ISO format in the CSV contract. Templates determine language; a voice override does not translate the text.

Success: `200 audio/mpeg`, binary MP3, `Content-Disposition: attachment; filename="payment_reminder.mp3"`, `Cache-Control: no-store`. `X-Request-ID` is server-generated. Audio is accumulated in bounded memory and discarded after response; no temporary files are created. The total provider operation is bounded to 45 seconds by default, including reading the stream. Requests exceeding capacity fail quickly.

| Status | Meaning |
|---|---|
| 401 | Missing or incorrect key |
| 422 | Invalid input or voice not enabled |
| 429 | TTS concurrency limit reached; Retry-After: 5 |
| 502 | Provider failed, no audio, or output too large |
| 504 | Provider operation exceeded deadline |

`POST /api/v1/voice/preview` uses the same input model and returns `{ "script": "...", "language": "en" }` without calling Microsoft. It does not reserve or send a reminder.

PowerShell example:

```powershell
$headers = @{ 'X-API-Key' = $env:REMINDER_API_KEY }
$body = @{
  customer_id='CUST001'; first_name='Juan'; bank_name='Example Fictional Bank'
  agent_name='Alex'; due_date='2026-11-15'
} | ConvertTo-Json
Invoke-WebRequest http://localhost:8000/api/v1/voice/generate -Method Post `
  -Headers $headers -ContentType application/json -Body $body -OutFile previews/manual.mp3
```

For Python-only TTS usage, install requirements, set `REMINDER_API_KEY`, omit `DATABASE_URL`, and start `uvicorn app.main:create_app --factory`. Tracking routes then return 503. `/health` is liveness. `/ready` checks the database when configured; it does not probe the online speech provider.

## Orchestration/tracking

`POST /api/v1/reminders/claim`

```json
{
  "row": {
    "customer_id": "CUST001", "first_name": "Juan", "email": "juan@example.com",
    "phone": "", "bank_name": "Example Fictional Bank", "agent_name": "Alex",
    "due_date": "2026-11-15", "reminder_eligible": "true"
  }
}
```

Returns `200` with `proceed=false`, `reminder_id`, and a sanitized reason for invalid, ineligible, duplicate, owned, exhausted, or cooling records. Valid email syntax is required even though the address is overridden. Extra CSV columns are invalid; map CRM fields explicitly. A missing optional phone is allowed. A malformed HTTP envelope returns 422.

A successful claim returns `proceed=true`, `reminder_id`, `token`, `dry_run`, `voice_request`, `script`, `sender`, `recipient`, `subject`, `body`. The recipient always comes from `TEST_RECIPIENT`, never from the row. Mode comes exclusively from server configuration.

`POST /api/v1/reminders/{reminder_id}/status`

```json
{ "token": "a-claim-uuid", "status": "failed", "error_code": "tts_failed" }
```

Use an actual UUID returned by claim. Allowed status values are `submitting`, `sent`, `failed`, `unknown`, `dry_run`, subject to the documented state machine. `failed` requires `tts_failed` or `preview_failed`; `unknown` requires `smtp_uncertain`. Free-form provider error text is never accepted. A stale/missing token, expired preparation lease, or invalid transition returns 409. Successful acknowledgement returns `{ "status": "..." }`. Tracking/database outages return sanitized 503 responses and halt delivery.

`GET /api/v1/reminders?limit=100` returns recent history (limit 1–1000), excluding ownership tokens and recipient information. Event history is available to operators via PostgreSQL `reminder_events`. No unauthenticated customer data endpoints exist.
