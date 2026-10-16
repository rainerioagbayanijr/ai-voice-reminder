# Automated personalized voice payment reminders

A working fictional-data MVP: n8n reads CSV, validates and atomically claims each reminder through FastAPI, requests a personalized Edge TTS MP3, and attaches it to an SMTP email. PostgreSQL records outcomes. No LLM or paid AI API is used.

**Default: dry run. Email mode always redirects to one independently verified test inbox. There is no real-customer delivery mode.** The bundled data is fictional. `sent` means SMTP submission was accepted; it does not mean inbox delivery or playback.

## Quick start

Prerequisites: Docker Desktop/Engine with Compose v2, internet access for images and Microsoft's online speech service, and an SMTP account only when testing external email.

```powershell
cd payment-reminder-mvp
python scripts/setup_env.py
# Creates .env with unique secrets and safe dry-run defaults; preserves an existing file.
docker compose up -d --build --wait
```

Use hexadecimal database passwords in this Compose configuration; other characters require URL encoding. Never commit `.env`.

1. Open [n8n](http://localhost:5678), create the local owner account, and import `workflows/payment_reminder.json` using **Import from File**.
2. Keep `DRY_RUN=true`. Execute the whole workflow from **Manual Trigger**. The seven-row sample produces four MP3 previews, skips one ineligible and one invalid record, and suppresses the repeated customer. Preview files appear in `previews/` and the n8n binary output. The claim node also shows the exact approved script.
3. Execute again: completed reminders are skipped. To create another intentional test cycle, use new fictional customer IDs or due dates. Do not erase successful history to bypass duplicates.
4. Inspect [API docs](http://localhost:8000/docs). API calls require `X-API-Key`; `/health` and `/ready` do not.

The workflow is imported inactive. Publish/activate it only when ready for the daily 09:00 Asia/Manila trigger. Manual execution works while inactive. Eligibility is the explicit CSV flag; the MVP does not infer an overdue or due-soon window from dates.

## Test email delivery

1. Independently confirm you own the test inbox. Set `TEST_RECIPIENT` to that single address, `TEST_RECIPIENT_VERIFIED=true`, `SENDER_EMAIL` to your SMTP provider's authorized sender, and `DRY_RUN=false` in `.env`.
2. Create an **SMTP** credential in n8n: host, port, TLS mode, username and password/app password. Keep certificate validation enabled. Select that credential in **Send Test Email** and save the workflow. Credentials stay encrypted in n8n; they are not embedded in the JSON export or CSV.
3. Run `docker compose up -d --wait` to apply configuration and execute the whole workflow. Dry-run history has a separate identity and does not suppress email tests.

Every recipient comes from the API's configured test override. CSV emails are validated but never used as delivery destinations. No CC or BCC is configured. Verification is an operator attestation, not an automated ownership challenge. For a fully local SMTP test with no account, use the integration harness below.

## Separate WhatsApp voice test

Import `workflows/whatsapp_voice_test.json` as **WhatsApp Voice Reminder - Test Only**. It defaults to **CSV input + preview**: n8n reads `data/customers.csv`, validates rows through the API, and generates one MP3 for each eligible, unique customer/due-date pair. The sample produces recordings for Juan, Maria, Ana and Luis; it skips Pedro, the invalid email row, and the repeated CUST001 row.

To send the batch to your own verified test phone, follow [the Meta setup guide](docs/whatsapp-test.md) and select `mode=send`. All recordings go to `test_recipient`; CSV phone numbers are never used. **Demo Settings** controls `agent_name` (`Rain from Test Company`) and `bank_name` (`Test Bank`). The test uses plain company and bank names, with a sentence pause between them. Names and due dates come from CSV. Select `input_mode=single` to use the configured sample customer Alex instead.

The current spoken opening is: “Hi, this is Rain from Test Company. Calling from Test Bank, regarding your payment due on November fifteenth, two thousand twenty-six.” The next line addresses the current CSV customer by name. To change the company or bank, edit Demo Settings and save; to change the wording, edit `app/templates/fil/voice.txt` and rebuild `tts-service`. Refresh n8n after a CLI workflow import before editing or running it.

This manual workflow has no schedule or automatic inbound trigger. Its mode is independent of email `DRY_RUN`. CSV duplicates are suppressed **within one execution only**; each new send-mode execution is another test batch. There is no durable WhatsApp duplicate ledger. Existing email tracking remains separate. See the guide for safe retry behavior and measured tests.

## Configuration and templates

- Edit `app/templates/<LANGUAGE>/voice.txt`, `subject.txt`, and `email.txt`, then rebuild the API. Allowed placeholders: `{first_name}`, `{agent_name}`, `{bank_name}`, `{due_date}`. Templates are validated at startup. No arbitrary Python expressions or custom SSML.
- The supplied `.env.example` selects Filipino: `fil-PH-BlessicaNeural`, `LANGUAGE=fil`, rate `-15%`, volume `-5%`. Existing `.env` files are preserved by setup; edit them explicitly to switch languages. Punctuation provides pauses; perceived tone requires listening and approval. `VOICE`, `ALLOWED_VOICES`, `RATE`, `VOLUME`, and `LANGUAGE` are environment settings. Requests may select only enabled voices. Prosody overrides are bounded to -50% through +20%.
- English (`en`) and Filipino (`fil`) sample templates ship. To select Filipino in `.env`, set `LANGUAGE=fil`, `VOICE=fil-PH-BlessicaNeural`, and add `fil-PH-BlessicaNeural` to `ALLOWED_VOICES`. Run `docker compose up -d --build --wait tts-service`. Dates are displayed as `November 15, 2026`. In Filipino voice scripts, the date is spelled out as `November fifteenth, two thousand twenty-six` to avoid Filipino number names. The Filipino voice script starts with an English introduction and continues in Filipino. These settings apply to both email and WhatsApp; they do not change recipients or send modes. Voice availability, pronunciation, tone and wording need review before real use; see `docs/tts-and-compliance.md`.
- `Settings` also accepts `TTS_TIMEOUT_SECONDS` (45), `MAX_CONCURRENCY` (2), `MAX_AUDIO_BYTES` (5 MB), `LEASE_SECONDS` (600), `MAX_ATTEMPTS` (3), and `RETRY_DELAY_SECONDS` (300). Pass these to the API container in Compose if changing them. Concurrency limits apply per API process.
- To change the CSV, replace `data/customers.csv`; n8n mounts it read-only. Keep the header and ISO dates. `reminder_eligible` accepts only `true`/`false`. `phone` is optional and unused.

## Tests

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check app scripts tests
# Real online speech, fictional names, no email:
$env:PYTHONPATH='.'
.venv/Scripts/python.exe scripts/tts_smoke.py
# Actual n8n + PostgreSQL + local SMTP capture, mocked speech boundary:
.venv/Scripts/python.exe scripts/e2e.py
# Same n8n workflow with real online speech, still only local SMTP capture:
.venv/Scripts/python.exe scripts/e2e.py --live
```

The test stack uses the separate `reminder-test` Compose project and the same local ports; stop a normal stack first with `docker compose stop`. The harness creates ignored test secrets, imports the actual workflow, captures attachments, repeats executions, and checks failure/recovery behavior. It does not relay email. Do not use `docker-compose.test.yml` for ordinary operation.

Database integration tests require `TEST_DATABASE_URL`; otherwise those tests are explicitly skipped. See `docs/testing.md` for exact commands and measured results. On Windows, asyncio and TestClient need local socket permissions. The test sink exposes captures only on loopback and should be stopped after testing.

## Operations

```powershell
docker compose ps
docker compose logs --tail 100 tts-service n8n
docker compose stop
docker compose start
docker compose down
```

`down` preserves history and credentials in named volumes. `down -v` destroys them and defeats duplicate protection; do not use it on retained data. Do not retry an SMTP node individually or replay a failed execution from its middle. Start a fresh execution from the trigger so the claim gate runs.

See [architecture](docs/architecture.md), [API contract](docs/api-contract.md), [deployment and recovery](docs/deployment.md), [testing](docs/testing.md), and [TTS/privacy/compliance findings](docs/tts-and-compliance.md). The [WhatsApp test workflow](docs/whatsapp-test.md) is a separate fictional demo; production WhatsApp, real-customer compliance controls, CRM and Viber remain future work.
