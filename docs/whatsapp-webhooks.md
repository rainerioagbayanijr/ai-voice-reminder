# Milestone 6: local WhatsApp webhook

The public callback is **`https://YOUR-TUNNEL.trycloudflare.com/webhooks/whatsapp`**.
The separate gateway exposes only this callback and a database health check. n8n,
the private API, credentials and audio previews are not exposed by the tunnel.

## Start the temporary tunnel

From the project folder, add these private `.env` settings:

```dotenv
WHATSAPP_APP_SECRET=your-meta-app-secret
WHATSAPP_WEBHOOK_VERIFY_TOKEN=your-random-verification-secret
WHATSAPP_PHONE_NUMBER_ID=your-meta-sender-phone-number-id
WHATSAPP_BUSINESS_ACCOUNT_ID=your-whatsapp-business-account-id
WHATSAPP_WINDOW_SOURCE=manual
```

The **App Secret** is in Meta App Settings → Basic. It is different from the
access token saved in n8n. Never commit either secret. The verification token is a
random value you choose; copy the same value into Meta's callback setup. The local
setup includes a generated verification token in `.env`; keep it private.

```powershell
docker compose build tts-service
docker compose --profile webhook up -d --wait tts-service n8n webhook-gateway webhook-tunnel
docker compose logs webhook-tunnel --tail 40
```

Copy the generated `https://....trycloudflare.com` URL and append
`/webhooks/whatsapp`. No Cloudflare account or purchased domain is needed.
Quick Tunnels are temporary development resources: their hostname can change
when restarted and they have no uptime guarantee. Keep Docker and the computer
running while testing. If the hostname changes, update Meta's callback URL.
[Cloudflare Quick Tunnel documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Connect Meta (one-time per callback URL)

1. In the correct Meta app, open WhatsApp's webhook configuration (the exact menu
   label may vary). Enter the callback URL above and the `.env` verification token.
2. Click **Verify and save**. Subscribe to the **messages** webhook field. Ensure
   this app is subscribed to the intended WhatsApp Business Account; a successful
   verification alone does not establish that subscription.
3. Send a new **Hello from your verified personal phone to Meta's test sender**.
   Messages received before configuring the subscription are not imported.
4. Check `docker compose logs webhook-gateway --tail 30`: a successful receipt
   logs `whatsapp_webhook` with `incoming: 1`. Duplicate deliveries log zero inserts.
   A dashboard sample with different sender/account IDs is deliberately ignored;
   use an actual message from your allowlisted phone to test the window.
5. Enable automatic windows in `.env`: `WHATSAPP_WINDOW_SOURCE=webhook`. Recreate
   the private API: `docker compose up -d --wait tts-service`.
6. Import the updated workflow JSON, preserving your Demo Settings and the Header
   Auth credential references on Upload/Send. Set **Demo Settings → window_source**
   to **`webhook`** and save. Its `phone_number_id` must match `.env`.
   `last_hello_at_utc` can now stay blank. The backend is authoritative: webhook
   mode never falls back to a supplied manual timestamp.
7. Execute the entire workflow using a new fictional test customer/reminder cycle
   if prior reminders were already submitted. Existing duplicate prevention stays
   active. Incoming Hello messages do not automatically execute the workflow.

The repository defaults to manual window mode for backwards compatibility until
the operator connects Meta. Sender/recipient verification and test overrides still
apply. Customer routing, if enabled later, uses each customer's own incoming event;
one test recipient's Hello cannot open another customer's window.

## What is recorded

- Incoming events: unique message ID, HMAC recipient fingerprint, sender ID,
  tenant, original event timestamp and receipt timestamp. Any supported actual
  user message opens the window; it does not have to contain the word Hello.
- Status events: unique message ID/status/timestamp, same routing identity,
  numeric error code. `sent`, `delivered`, `read` and `failed` are supported.
- No text, profile names, raw JSON, raw recipient phones or provider error bodies
  are persisted or logged. Do not rotate `REMINDER_API_KEY` casually: existing
  recipient fingerprints depend on it. There is no automatic retention policy
  yet; production retention/cleanup is deferred with milestone 7.

The authenticated `GET /api/v1/whatsapp/reminders` history now includes
`delivery_status`, `delivery_status_at`, and `delivery_error_code`. Submission
`status` is kept separate. A read receipt does not prove that audio was played.
Read takes precedence over delivered; both take precedence over failure/sent, so
late notifications do not downgrade an established delivery/read state. All
events remain in `whatsapp_delivery_events` for review. Receipts that arrive
before the submission acknowledgement are stored and automatically appear once
its message ID is recorded. Failed delivery never automatically resends a
submitted reminder. An unknown send without a recorded message ID stays held
for review; a receipt cannot safely guess which reminder it belongs to.

## Verification and failure handling

GET verification checks `hub.mode`, constant-time token equality and returns the
plain challenge. POST verifies `X-Hub-Signature-256` over the **raw bytes** using
HMAC-SHA256 with the App Secret before parsing. Account and sender IDs must match
the configured integration. Requests are limited to 1 MB. PostgreSQL unique keys
and transactions deduplicate concurrent retries. A database failure returns 503
so Meta can retry; invalid signature is 401, invalid signed notification is 400,
oversized body is 413. No provider calls or message sends run in this endpoint.

The webhook receipt uses Meta's event time, not server receipt time, so replaying
an old notification cannot refresh a window. The newest recorded incoming event
is used. Claim and reservation retain their existing safety margins near expiry.

## Stop / troubleshooting

```powershell
docker compose --profile webhook stop webhook-tunnel webhook-gateway
```

- Callback verification fails: check URL/path and verification token; ensure
  gateway/tunnel are running. Verification token and App Secret are different.
- POST returns 503: set App Secret, sender and account IDs, recreate the gateway,
  and check PostgreSQL health.
- POST returns 401: use the App Secret of the same Meta app, not its access token.
- No incoming events: check the messages subscription, WABA app subscription,
  allowed test recipient, account/sender IDs and current tunnel URL.
- `reply_window_required`: send a fresh message after the subscription is active;
  verify `incoming: 1`, matching IDs and webhook mode on the backend/workflow.
- `duplicate_or_review_required`: use a new fictional test ID/cycle; do not delete
  the ledger or change institution identity to force a resend.

## Code review

- `app/webhook_main.py`: isolated public API, verification, body/signature checks.
- `app/services/webhooks.py`: parsing and durable, deduplicated ingestion.
- `app/services/whatsapp.py`: verified reply windows and delivery history join.
- `app/schema.sql`: additive event tables/index; existing ledgers preserved.
- `docker-compose.yml`: optional `webhook` profile, gateway and Cloudflare tunnel.
- `tests/test_webhooks.py`: endpoint/security and real PostgreSQL state tests.

Meta's primary developer pages returned HTTP 429 during implementation research.
The signature/challenge mechanism was cross-checked against Meta's official
[webhook SDK reference](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/webhooks/start/)
(archived SDK, used only as protocol reference), with message-ID status tracking
documented in Meta's official [Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/folder/o48mro7/messages).
The adapter uses direct HTTP, not that SDK.
