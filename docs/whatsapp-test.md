# WhatsApp voice reminder — separate test workflow

Importable file: `workflows/whatsapp_voice_test.json`

n8n name: **WhatsApp Voice Reminder - Test Only**

This separate workflow reads fictional customers from `data/customers.csv` and generates a personalized recording for each eligible row. All sends are redirected to your own verified WhatsApp test phone. It reuses the existing speech API and CSV mount. It does not use SMTP or alter the email workflow or its credentials.

**Tracking upgrade:** Send mode now uses a durable WhatsApp PostgreSQL ledger. Configure the
backend test recipient as well as Demo Settings before sending; see
[tracking, retries and customer routing](whatsapp-reliability.md). Customer routing is an additional,
explicitly enabled path, disabled by default. The steps below describe test routing.

Defaults are `input_mode=csv` and `mode=preview`. No Meta account is needed for preview. Internet is needed for real Edge TTS. The current seven-row CSV yields four previews: Juan, Maria, Ana and Luis. One ineligible row, one invalid row and one duplicate are skipped. Set `input_mode=single` to test Alex from Demo Settings instead.

See [native voice-note testing](whatsapp-voice-notes.md) for the format upgrade and phone-test steps.

## Try preview now

1. Start the existing stack with `docker compose up -d --wait`.
2. Open n8n, import `workflows/whatsapp_voice_test.json`, and open **WhatsApp Voice Reminder - Test Only**. If it was already imported for you, open that workflow instead of importing another copy.
3. Execute the entire workflow from **Start WhatsApp Test**. Leave **Demo Settings** at its defaults.
4. Open **Preview Complete** to inspect/download its `audio` binary. The OGG/Opus recording also appears in the host `previews` folder as `whatsapp-<execution-id>-<customer-id>.ogg`.

Rain from Test Company and Test Bank are fictional demo identities, configurable in Demo Settings as `agent_name` and `bank_name`. In CSV mode, each row supplies the customer name and due date; the configured agent and bank override CSV institution/agent values for this test. The spoken date uses explicit English words, such as “November fifteenth, two thousand twenty-six.” Preview before sending to review pronunciation. All three language templates still use the supported `{due_date}` placeholder; only voice speech expands its digits into words.

## Edit the spoken message

The current opening is:

> Hi, this is Rain from Test Company. Calling from Test Bank, regarding your payment due on November fifteenth, two thousand twenty-six.

The following line addresses each customer by their CSV first name. Plain company and bank names replaced the acronym examples after listening feedback; a full stop provides a pause after the agency introduction.

- **Company and bank:** edit `agent_name` and `bank_name` in Demo Settings. The current agent field includes both the agent and company: `Rain from Test Company`.
- **Customer name and date:** edit `data/customers.csv` in CSV mode. `first_name` and `due_date` in Demo Settings apply only to single mode.
- **Sentence wording:** edit `app/templates/fil/voice.txt`, preserve its placeholders, and run `docker compose up -d --build --wait tts-service`.
- **After a CLI workflow import:** refresh n8n before editing or executing, so the browser loads the saved configuration.

Preview files persist in the host `previews` folder. Send mode uploads audio to Meta; it does not also save a copy in that project folder. n8n handles transient binary data in its persistent volume, subject to cleanup.

CSV rows are validated in Python, independently. Valid email syntax remains required by the shared customer schema, although CSV email and phone are never delivery destinations in this workflow. Duplicate customer IDs and due dates are skipped within a batch. Batch size is limited to 1,000 rows. CSV input can later be replaced by a CRM node producing the same rows.

## Create the free Meta test resources

Use Meta directly; no Twilio, BSP subscription, paid hosting, or tunnel is required for this manually triggered outbound test.

1. Open the [Meta developer dashboard](https://developers.facebook.com/apps/) and create an app with the WhatsApp business-messaging use case. Complete Meta's developer-account checks and select/create the required business portfolio as its setup asks.
2. Follow the WhatsApp **Get started / API Setup / API Testing** screens. Labels can change. Select the **Meta-provided test number**, rather than registering a production business number.
3. Add your own WhatsApp phone to the test recipient list and complete the verification code. Copy your full number with country code.
4. Generate the temporary test access token. Copy the **Phone Number ID** and the **Graph API version** shown in Meta's sample request. Phone Number ID is not the displayed test phone number, Business Account ID, or app ID.
5. Use Meta's sample-message test first. Confirm that it arrives on your phone. If a billing/card prompt appears, stop and verify that you selected the developer test resources; this project does not configure billing or promise a free production number.

Meta advertises [free test numbers and sandbox resources](https://whatsappbusiness.com/developers/developer-hub/). Live receipt from a Meta test sender was confirmed during the original single-customer demonstration on 16 October 2026; account credentials are not included in this repository. Account availability, recipient limits and token expiry are controlled by Meta. The temporary token may expire; generate a replacement when needed. This test does not require production business verification or production billing to be configured by our code.

## Save the token securely in n8n

Open **Upload Voice Note to Meta** and create/select a **Header Auth** credential:

| Credential field | Value |
|---|---|
| Name | `Authorization` |
| Value | `Bearer YOUR_META_TEST_ACCESS_TOKEN` |

`Bearer` is followed by one space and the actual generated token. Give the credential a recognizable name such as **Meta WhatsApp Test**. Select that same credential on **Send WhatsApp Audio**.

Do not put the token in Demo Settings, source control, a chat message, a URL, or an environment example. The exported workflow contains no token or actual credential ID. Header Auth has no Meta-specific connection test; use Meta's sample request and inspect the API node output if sending fails.

## Send your first voice note

1. Configure `WHATSAPP_TEST_RECIPIENT` and `WHATSAPP_TEST_RECIPIENT_VERIFIED=true` in `.env`, keep `WHATSAPP_CUSTOMER_ROUTING_ENABLED=false`, and rebuild/recreate `tts-service`. On your verified phone, reply **Hello** in the chat with Meta's test number. You do **not** wait 24 hours. This opens the window for ordinary replies immediately.
2. Immediately after sending Hello, obtain its approximate UTC time in PowerShell:

   ```powershell
   (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
   ```

3. Open **Demo Settings** in n8n and edit its JSON:

   | Field | What to enter |
   |---|---|
   | `mode` | `"send"` |
   | `routing_mode` | `"test"`; backend override is enforced |
   | `institution_id` | Stable `"demo-bank"`; do not change to bypass duplicate protection |
   | `input_mode` | `"csv"` for the CSV batch, or `"single"` for one sample |
   | `first_name` | Sample name used only in single mode, such as `"Alex"` |
   | `agent_name` | `"Rain from Test Company"` for this demo |
   | `bank_name` | `"Test Bank"` for this demo |
   | `due_date` | Single-mode date in `YYYY-MM-DD`; CSV mode uses each row’s due date |
   | `test_recipient` | Your verified number, including country code; digits, optionally a leading `+`; no spaces |
   | `phone_number_id` | The Meta test sender's Phone Number ID, as a JSON string |
   | `graph_api_version` | The version from Meta's sample request, in the form `vXX.0` |
   | `last_hello_at_utc` | The actual UTC time from step 2, ending in `Z` |
   | `meta_test_number_confirmed` | Boolean `true`, after confirming the sender is Meta's test resource |
   | `recipient_verified` | Boolean `true`, after verifying your own recipient phone in Meta |

   Keep IDs and timestamps in double quotes. Keep booleans unquoted. The empty/default fields intentionally prevent sending until configured.

4. Save and execute the entire workflow from **Start WhatsApp Test**.
5. CSV mode reads and validates the batch, then **Each WhatsApp Customer** processes one row at a time. Eligible rows go through speech, upload and send; skipped rows continue without synthesis. **Batch Complete** lists per-customer outcomes and counts.
6. `WhatsApp Result.status = submitted` with a `wamid...` message ID means Meta accepted the request. Check your phone and tap Play. API acceptance does not prove delivery, reading, or playback.

The timestamp and verification flags are operator attestations; this manual workflow does not independently receive or verify the inbound Hello. The window is checked before synthesis and again after upload, with a small safety margin. Meta remains the authority on whether the actual conversation window is open. Editing the timestamp without sending Hello will not open a Meta reply window.

## What this test does and does not automate

- Each eligible CSV customer produces one message to the configured test phone. The CSV is never used to select recipients. No production phone, scheduled reminders or background sending are configured.
- Sending Hello does **not** itself trigger this manual workflow. You click Execute afterward. This avoids adding a public HTTPS webhook/tunnel, webhook verification, and another credential setup to the first demo.
- Upload and TTS requests have bounded retries. **The send request has no automatic retry**, because an interrupted response may conceal an accepted submission.
- Every send-mode execution checks a durable WhatsApp ledger before generating audio. Previously submitted, submitting, unknown or rejected reminders are skipped across executions/restarts. Safe preparation failures can retry on a later full run after the configured delay, within the attempt limit. Never rerun the send node alone. Old pre-upgrade sends have no ledger entries and are not automatically reconstructed. Webhook integration remains future work.
- OGG/Opus audio is sent with `audio.voice=true` to request a native voice note. Verify appearance/playback on your phone. It is not a voice call; transcription availability is controlled by WhatsApp.
- Changing `.env`'s email `DRY_RUN` has no effect on this workflow. Change `mode` in **Demo Settings**.

## Results and errors

| Result | Meaning / action |
|---|---|
| `preview` | OGG/Opus preview saved; no Meta request was made |
| Validation error | Fix the named setting; no TTS/upload/send was attempted |
| `failed`, stage `tts` | No media upload or message attempt; inspect the TTS node |
| `failed`, stage `upload` | No message attempted; inspect token, version, recipient setup and upload error |
| Window expired after upload | Media may be uploaded, but no message was attempted; send a fresh Hello |
| `submitted` | Meta returned a message ID; check your phone |
| `unknown` | Send failed or returned no valid message ID; inspect the API response and phone before any manual retry |
| `rejected` | Explicit permanent provider rejection; held for review, no automatic retry |
| `held_for_review` | Reservation/outcome acknowledgement was uncertain; no automatic resend |
| `skipped` | Ineligible/invalid/duplicate, already processed, waiting for backoff, or retry limit reached |
| `tracking_error` | Claim unavailable or routing blocked; no TTS/upload/send for that row |

Expired tokens, wrong Phone Number IDs, unverified test recipients, a closed reply window and unavailable test resources are common account/setup failures. Do not replace the API host, disable certificate verification, or add a payment method just to bypass a failed test.

## Verification

Code-node guard tests: `python -m pytest -q tests/test_whatsapp_workflow.py`

Actual n8n upload/send transport tests with local mock endpoints:

```powershell
.venv/Scripts/python.exe scripts/test_whatsapp_e2e.py
```

The harness starts disposable n8n/API/mock containers on an internal Docker network and a disposable PostgreSQL database. Only the database also has a bridge connection with a loopback-only published port for host pytest. It tests persistent tracking, multipart transfer, test and per-customer routing, duplicate reruns, bounded recovery and uncertain sends. A generated tone passes through the real API/FFmpeg converter, and ffprobe verifies the uploaded Opus stream. It proves encoding and transport, not spoken quality. No real Meta credentials are used. The ordinary n8n and email workflow are not modified by the harness. See the reliability guide for details.

A live preview in the ordinary n8n instance verifies the real speech endpoint separately. Live receipt was confirmed during the original Meta test-number demonstration. Automated CSV submission tests use mock Meta endpoints; confirm receipt on your configured phone when testing your own saved token.

Initial single-customer measurements on 16 October 2026:

- 24 WhatsApp guard/contract tests passed. The full Python suite had 62 passes and 12 database-test skips because no test database URL was supplied; application/database code was unchanged.
- All 7 actual-n8n mock scenarios passed on the isolated network, including lost acknowledgement and expired-window rejection. The test containers and network were removed afterward.
- The separate workflow imported successfully into n8n 2.43.6 without a Meta credential. Its real preview execution finished at **Preview Complete**, produced `previews/whatsapp-8.mp3` (148,896 bytes, valid MP3 header), and executed neither upload nor send node.
- The normal API, n8n and PostgreSQL services stayed healthy. The email workflow, its credentials, CSV and environment settings were not changed by this addition.

Historical CSV and spoken-wording checks on 16 October 2026 (before the tracking upgrade):

- The full suite passed 81 tests, with 12 database tests skipped because no test database URL was supplied. Ruff passed.
- Nine isolated n8n transport scenarios passed during CSV integration, including distinct customer names/dates, unique preview filenames, fixed test-recipient routing and invalid/ineligible/duplicate skips.
- With the final Test Company / Test Bank wording, the real n8n CSV preview produced four fresh MP3s for Juan, Maria, Ana and Luis and skipped three rows. No Meta send node ran during that preview.
- The exact rendered opening and English date words were checked through `/api/v1/voice/preview`. Byte, script and transport checks do not replace listening review.

## Financial-services scope

This is a fictional, owner-only transport demonstration, not approval for real financial-services messaging. Meta lists ordinary payment reminders under [utility messages](https://whatsappbusiness.com/products/conversation-categories/utility/) but lists debt collection under [prohibited services](https://whatsappbusiness.com/policy/). Audio does not create an exemption. Confirm eligibility before adopting any real customer use case. Outside the actual 24-hour window, approved-template rules apply; this workflow does not attempt an audio-template workaround.
