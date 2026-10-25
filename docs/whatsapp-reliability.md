# WhatsApp tracking, recovery and routing

For automatic verified reply windows and delivery receipts, see
[milestone 6 webhook setup](whatsapp-webhooks.md). The manual timestamp instructions
below apply only when `WHATSAPP_WINDOW_SOURCE=manual`.

This upgrade adds durable processing to the existing manual WhatsApp workflow. The spoken template,
speech provider and email workflow are retained, and no schedule is activated. WhatsApp now uses
OGG/Opus and the voice-message flag; see [voice-note testing](whatsapp-voice-notes.md).
Public workflow defaults remain `mode=preview`, `routing_mode=test`.

## Configure test sends

In `.env`, set `WHATSAPP_TEST_RECIPIENT` to your own verified international phone (country code,
digits, optional leading `+`) and set `WHATSAPP_TEST_RECIPIENT_VERIFIED=true` after verifying it.
Keep `WHATSAPP_CUSTOMER_ROUTING_ENABLED=false`. Rebuild/recreate the API:

```powershell
docker compose up -d --build --wait tts-service
```

Import the updated `workflows/whatsapp_voice_test.json`. Preserve/select your existing Header Auth
credential on Upload Voice Note to Meta and Send WhatsApp Audio; no credential export is needed. In Demo Settings set:

- `mode=send`, `routing_mode=test`, and a stable `institution_id` such as `demo-bank`.
- `test_recipient` to the same phone configured on the backend.
- Your existing sender Phone Number ID and Graph API version.
- The actual recent incoming Hello timestamp, plus the existing test-verification flags.

Run from **Start WhatsApp Test**. CSV names/dates still personalize each recording. Backend test
routing ignores CSV destination phones. The API fails closed if its recipient configuration is
missing, unverified, or disagrees with the workflow. Email `DRY_RUN` does not control WhatsApp.

Preview remains repeatable without Meta credentials or a configured test phone. Preview does not
claim a send identity and cannot suppress a later send.

## Customer routing

This path is implemented for controlled testing; it stays disabled by default. It requires both
`routing_mode=customer` in the workflow and `WHATSAPP_CUSTOMER_ROUTING_ENABLED=true` on the API.
It only accepts CSV input. Each eligible row must have its own international `phone` and its own
`last_hello_at_utc` column ending in `Z`. Never enable it against the bundled fictional phone numbers.
Use only numbers you control for acceptance testing.

The shared customer schema still validates CSV email syntax; email is not used for WhatsApp
delivery. Missing/bad phones or missing/expired per-customer reply windows are skipped. The global
test Hello timestamp is never substituted for another customer's timestamp. These timestamps are
operator attestations until authenticated inbound webhooks are implemented; no automatic verification
of the conversation window or customer ownership is claimed.

## Processing and duplicate identity

```text
CSV → validate rows → claim reminder → generate speech + convert to OGG/Opus → upload media
    → reserve send once → send voice note once → acknowledge outcome → next customer
```

FastAPI owns routing validation and PostgreSQL transactions; n8n owns orchestration/provider I/O.
Separate `whatsapp_reminders` and `whatsapp_events` tables are created under the existing startup
migration lock. Existing email tables and records are untouched. A primary key plus row lock gives
one processing owner under overlapping executions. No transaction spans a provider request.

Identity includes backend tenant, stable institution ID, customer ID, due date, WhatsApp channel,
and test/customer routing mode. Changing names, voice, script, sender, recipient or execution ID
does not bypass an already submitted reminder. Keep institution IDs stable. Test and customer
identities are separate. Existing sends from the old workflow have no ledger entries: they cannot
be automatically reconstructed or deduplicated. Review this before the first send after upgrade.

Only validated send candidates enter this ledger. Invalid, ineligible and within-batch duplicate
rows appear in the workflow batch summary. Preview results also remain workflow/file outputs.

## Retry and recovery

| State | Meaning | Later full-workflow execution |
|---|---|---|
| processing | Preparation owner holds a token and lease | Skip while leased; reclaim after expiry |
| failed | No send occurred, or recognized rate-limit rejection | Retry after delay, within attempt limit |
| submitting | Single-use permission was issued | Hold for review; never auto-reclaim |
| submitted | Meta returned a message ID | Skip; delivery/read not established |
| unknown | Timeout, disconnect, 5xx or ambiguous response | Hold for review; no automatic resend |
| rejected | Explicit permanent 4xx rejection | Hold for review; no automatic resend |

Defaults: processing lease 600 seconds, maximum 3 claims, retry delay 300 seconds. These settings
are shared with email; pass `LEASE_SECONDS`, `MAX_ATTEMPTS`, `RETRY_DELAY_SECONDS` to the API
container if overriding. A claim counts as one attempt; n8n may make up to three TTS requests and
two upload requests within it. Media upload does not send a customer message.

Only explicit HTTP 400/429 responses with Meta error code 130429 or 131056 qualify as retryable send
rejections. Other uncertain send outcomes are held. Send and reservation nodes have no automatic
HTTP retry. Terminal status acknowledgement can retry idempotently. A lost claim response leaves
a recoverable processing lease; a lost reservation response leaves a held `submitting` record.
If outcome recording fails, the summary reports `held_for_review`; the existing reservation still
protects against a duplicate send.

Retries are coordinated by a **later whole-workflow execution**, not a background retry worker or
new schedule. Never resume directly at the Send node. Never erase successful history or change
institution/customer IDs to force real reminders through. For a new intentional fictional test
cycle, use distinct test records. Do not clear retained database volumes.

Inspect authenticated `GET /api/v1/whatsapp/reminders` and compare message IDs with provider
evidence for held records. There is deliberately no automatic unlock/requeue endpoint for uncertain
sends. Resolve those operationally after review; a future release can add an audited resolution UI.
Exactly-once external delivery is not guaranteed: a crash after reservation can leave an unsent
reminder held, while a lost provider acknowledgement can leave an accepted reminder uncertain.

## Storage and security

The ledger stores customer references, due dates, sender IDs, message IDs and sanitized error codes.
It does not store names, email, scripts, tokens for Meta, raw phone numbers or audio. Recipient binding
uses an HMAC with the API key, so phone guessing requires that secret. Rotating the API key prevents
old processing reservations from validating; let those preparation claims expire and reclaim them.
Submitted/unknown protection depends on stable identity, not that fingerprint.

Claim tokens and destinations are transported through n8n for processing, so execution saving remains
disabled. Preview files retain the existing cleanup behavior. Back up PostgreSQL to preserve deduplication.

## Verification

`python scripts/test_whatsapp_e2e.py` runs the full pytest suite against a disposable PostgreSQL
database, then imports and executes the actual workflow in disposable n8n. n8n, FastAPI and mock
provider containers use an internal Docker network. Only the disposable PostgreSQL container is
also attached to Docker's bridge to expose its randomized loopback-only port for host pytest.
No real Meta token, speech provider or customer destination is used. Containers/networks are cleaned
up in `finally`; diagnostic logs are saved under ignored `.verification/`.

The tests cover concurrent claims, restart persistence, stale leases/tokens, backoff/attempt limits,
recipient binding, per-row routing, duplicate reruns, TTS recovery, lost acknowledgement and explicit
rate-limit recovery. Live delivery remains a separate operator acceptance test. Voice-note transport
tests use the real API/FFmpeg converter with a local tone source and verify the uploaded Opus stream
with ffprobe.
