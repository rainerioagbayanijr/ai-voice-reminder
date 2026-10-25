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

## Generic customer preparation (retained API)

`POST /api/v1/customers/prepare` requires `X-API-Key` and accepts `{"rows": [...]}` with 1–1,000 CSV row objects using the shared customer schema. It requires no tracking database and makes no speech or delivery requests.

The response is `{"customers": [...]}`, preserving row order. Each valid, eligible row returns `status=eligible`, its row index and customer ID, and a normalized `voice_request`. Other rows return `status=skipped` and one of `invalid_customer`, `ineligible`, or `duplicate_in_batch`. Email addresses, phone numbers and raw validation inputs are excluded from the response. Duplicate identity is customer ID plus due date, within this request only. It is not a durable send ledger.

The updated WhatsApp workflow uses the channel-specific preparation endpoint below so it can retain per-row routing information. Agent/bank overrides and CSV customer names/dates are preserved.

## WhatsApp tracking extension

Speech provider selection is server-only (`TTS_PROVIDER=edge` by default). The optional ElevenLabs
adapter uses the same request schema and MP3/OGG response contract. A request's `voice` is an ID
from the selected provider's allowlist, not a provider selector. ElevenLabs rejects nonzero `volume`
and rates outside its supported speed range with 422 before any upstream call. See
[provider configuration](speech-providers.md). The WhatsApp nodes and credential setup do not change.

WhatsApp now calls `POST /api/v1/voice/generate?audio_format=ogg_opus` with the same voice-request
JSON. It returns `audio/ogg` and filename `payment_reminder.ogg`. Omitting `audio_format` retains
MP3/email behavior. Any format other than `mp3` or `ogg_opus` returns 422. Converter saturation,
decode failure, missing executable and deadline expiration return sanitized 429, 502, 503 and 504
respectively. WhatsApp reservations now issue `audio:{id:media_id,voice:true}`. See
[voice-note setup](whatsapp-voice-notes.md).

All endpoints require the existing `X-API-Key`. See [routing and recovery](whatsapp-reliability.md).

| Endpoint | Input / output |
|---|---|
| `POST /api/v1/whatsapp/customers/prepare` | `{rows:[CSV rows]}` → independent eligible/skipped results; eligible rows retain phone and per-row Hello timestamp, omit email |
| `POST /api/v1/whatsapp/reminders/claim` | `{row,institution_id,routing_mode,phone_number_id,test_recipient,last_hello_at_utc}` → `{proceed,reminder_id,token,recipient,voice_request}` or skip reason |
| `POST /api/v1/whatsapp/reminders/{id}/reserve` | `{token,recipient,media_id}` → one-time `{proceed,phone_number_id,payload}`; expired window returns `proceed:false` |
| `POST /api/v1/whatsapp/reminders/{id}/outcome` | `{token,status,error_code?,message_id?}` → acknowledged status; exact terminal acknowledgements are idempotent |
| `GET /api/v1/whatsapp/reminders?limit=100` | Sanitized history, maximum 1,000 rows; no raw phone or claim token |

`routing_mode` is `test` (default) or `customer`. Disabled/misconfigured routing returns 403.
Stale tokens, invalid transitions and repeated reservations return 409. Database outages return
sanitized 503 responses. A reserve call must never be automatically retried. Customer reply-window
timestamps in manual mode come from each row; test mode uses the workflow's global timestamp.
With `WHATSAPP_WINDOW_SOURCE=webhook`, both use recorded, signed incoming notifications instead.
`submitted` confirms provider acceptance only, not delivery or playback.

## Optional public WhatsApp webhook

The isolated gateway (port 8001 inside Docker; no host port) serves only
`GET /webhooks/whatsapp`, `POST /webhooks/whatsapp` and `GET /health`.
GET uses Meta verification token/challenge; POST uses the App Secret HMAC signature,
not `X-API-Key`. See [setup and response codes](whatsapp-webhooks.md).
Authenticated private reminder history adds `delivery_status`, `delivery_status_at`
and `delivery_error_code`; the existing submission state remains separate.
