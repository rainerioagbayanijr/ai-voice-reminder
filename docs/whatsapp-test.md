# WhatsApp voice reminder — separate test workflow

Importable file: `workflows/whatsapp_voice_test.json`

n8n name: **WhatsApp Voice Reminder - Test Only**

This workflow generates one fictional personalized recording and, when configured, sends it as an MP3 audio message to your own verified WhatsApp test phone. It reuses the existing FastAPI speech endpoint. It does not use the customer CSV or SMTP, and it does not change the email workflow or its saved credentials.

The default `mode` is `preview`, independent of the email service's `DRY_RUN` setting. No Meta account is needed for preview. Internet is still needed for real Edge TTS.

## Try preview now

1. Start the existing stack with `docker compose up -d --wait`.
2. Open n8n, import `workflows/whatsapp_voice_test.json`, and open **WhatsApp Voice Reminder - Test Only**. If it was already imported for you, open that workflow instead of importing another copy.
3. Execute the entire workflow from **Start WhatsApp Test**. Leave **Demo Settings** at its defaults.
4. Open **Preview Complete** to inspect/download its `audio` binary. The recording also appears in the host `previews` folder as `whatsapp-<execution-id>.mp3`.

The sample says the institution is fictional. `first_name` in Demo Settings controls the sample name. The fixed fictional due date is 15 November 2026. No real customer information is used.

## Create the free Meta test resources

Use Meta directly; no Twilio, BSP subscription, paid hosting, or tunnel is required for this manually triggered outbound test.

1. Open the [Meta developer dashboard](https://developers.facebook.com/apps/) and create an app with the WhatsApp business-messaging use case. Complete Meta's developer-account checks and select/create the required business portfolio as its setup asks.
2. Follow the WhatsApp **Get started / API Setup / API Testing** screens. Labels can change. Select the **Meta-provided test number**, rather than registering a production business number.
3. Add your own WhatsApp phone to the test recipient list and complete the verification code. Copy your full number with country code.
4. Generate the temporary test access token. Copy the **Phone Number ID** and the **Graph API version** shown in Meta's sample request. Phone Number ID is not the displayed test phone number, Business Account ID, or app ID.
5. Use Meta's sample-message test first. Confirm that it arrives on your phone. If a billing/card prompt appears, stop and verify that you selected the developer test resources; this project does not configure billing or promise a free production number.

Meta advertises [free test numbers and sandbox resources](https://whatsappbusiness.com/developers/developer-hub/). This has not been provisioned or verified on your account. Account availability, recipient limits and token expiry are controlled by Meta. The temporary token may expire; generate a replacement when needed. This test does not require production business verification or production billing to be configured by our code.

## Save the token securely in n8n

Open **Upload MP3 to Meta** and create/select a **Header Auth** credential:

| Credential field | Value |
|---|---|
| Name | `Authorization` |
| Value | `Bearer YOUR_META_TEST_ACCESS_TOKEN` |

`Bearer` is followed by one space and the actual generated token. Give the credential a recognizable name such as **Meta WhatsApp Test**. Select that same credential on **Send WhatsApp Audio**.

Do not put the token in Demo Settings, source control, a chat message, a URL, or an environment example. The exported workflow contains no token or actual credential ID. Header Auth has no Meta-specific connection test; use Meta's sample request and inspect the API node output if sending fails.

## Send your first audio message

1. On your verified phone, reply **Hello** in the chat with Meta's test number. You do **not** wait 24 hours. This opens the window for ordinary replies immediately.
2. Immediately after sending Hello, obtain its approximate UTC time in PowerShell:

   ```powershell
   (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
   ```

3. Open **Demo Settings** in n8n and edit its JSON:

   | Field | What to enter |
   |---|---|
   | `mode` | `"send"` |
   | `first_name` | A fictional sample name, such as `"Alex"` |
   | `test_recipient` | Your verified number, including country code; digits, optionally a leading `+`; no spaces |
   | `phone_number_id` | The Meta test sender's Phone Number ID, as a JSON string |
   | `graph_api_version` | The version from Meta's sample request, in the form `vXX.0` |
   | `last_hello_at_utc` | The actual UTC time from step 2, ending in `Z` |
   | `meta_test_number_confirmed` | Boolean `true`, after confirming the sender is Meta's test resource |
   | `recipient_verified` | Boolean `true`, after verifying your own recipient phone in Meta |

   Keep IDs and timestamps in double quotes. Keep booleans unquoted. The empty/default fields intentionally prevent sending until configured.

4. Save and execute the entire workflow from **Start WhatsApp Test**.
5. The path should be **Generate Demo MP3 → MP3 Ready → Preview Only (false) → Upload MP3 to Meta → Upload Accepted → Check Window and Prepare Audio → Send WhatsApp Audio → WhatsApp Result**.
6. `WhatsApp Result.status = submitted` with a `wamid...` message ID means Meta accepted the request. Check your phone and tap Play. API acceptance does not prove delivery, reading, or playback.

The timestamp and verification flags are operator attestations; this manual workflow does not independently receive or verify the inbound Hello. The window is checked before synthesis and again after upload, with a small safety margin. Meta remains the authority on whether the actual conversation window is open. Editing the timestamp without sending Hello will not open a Meta reply window.

## What this test does and does not automate

- One fictional sample goes to exactly the configured recipient per send-mode execution. No CSV/customer batch, production phone, scheduled reminders, or background sending is configured.
- Sending Hello does **not** itself trigger this manual workflow. You click Execute afterward. This avoids adding a public HTTPS webhook/tunnel, webhook verification, and another credential setup to the first demo.
- Upload and TTS requests have bounded retries. **The send request has no automatic retry**, because an interrupted response may conceal an accepted submission.
- Every manual send-mode run is a fresh attempt. This demo does not use the email reminder ledger or provide its durable duplicate prevention. Do not repeatedly click Execute, run overlapping tests, or rerun the send node alone. If you need automatic inbound triggers, durable idempotency, or delivery webhooks later, implement those as a separate extension.
- A normal MP3 audio message is sent. It is not a WhatsApp voice call. A specific voice-note bubble/transcription behavior is not promised.
- Changing `.env`'s email `DRY_RUN` has no effect on this workflow. Change `mode` in **Demo Settings**.

## Results and errors

| Result | Meaning / action |
|---|---|
| `preview` | MP3 saved; no Meta request was made |
| Validation error | Fix the named setting; no TTS/upload/send was attempted |
| `failed`, stage `tts` | No media upload or message attempt; inspect the TTS node |
| `failed`, stage `upload` | No message attempted; inspect token, version, recipient setup and upload error |
| Window expired after upload | Media may be uploaded, but no message was attempted; send a fresh Hello |
| `submitted` | Meta returned a message ID; check your phone |
| `unknown` | Send failed or returned no valid message ID; inspect the API response and phone before any manual retry |

Expired tokens, wrong Phone Number IDs, unverified test recipients, a closed reply window and unavailable test resources are common account/setup failures. Do not replace the API host, disable certificate verification, or add a payment method just to bypass a failed test.

## Verification

Code-node guard tests: `python -m pytest -q tests/test_whatsapp_workflow.py`

Actual n8n upload/send transport tests with local mock endpoints:

```powershell
.venv/Scripts/python.exe scripts/test_whatsapp_e2e.py
```

The harness starts disposable n8n/mock containers on a Docker network with **no internet route**. It tests multipart MP3 transfer, exact recipient routing, preview, upload failure, TTS failure, send failure, lost acknowledgement, and expired-window rejection. Fixture audio is deliberately not playable; it proves transport only. It uses no real Meta credentials and cleans up its own containers/network. The ordinary n8n and email workflow are not modified by the test harness.

A live preview in the ordinary n8n instance verifies the real speech endpoint separately. **Actual WhatsApp delivery remains unverified until you create the Meta test resources and select your token.**

Measured on 16 October 2026:

- 24 WhatsApp guard/contract tests passed. The full Python suite had 62 passes and 12 database-test skips because no test database URL was supplied; application/database code was unchanged.
- All 7 actual-n8n mock scenarios passed on the isolated network, including lost acknowledgement and expired-window rejection. The test containers and network were removed afterward.
- The separate workflow imported successfully into n8n 2.43.6 without a Meta credential. Its real preview execution finished at **Preview Complete**, produced `previews/whatsapp-8.mp3` (148,896 bytes, valid MP3 header), and executed neither upload nor send node.
- The normal API, n8n and PostgreSQL services stayed healthy. The email workflow, its credentials, CSV and environment settings were not changed by this addition.

## Financial-services scope

This is a fictional, owner-only transport demonstration, not approval for real financial-services messaging. Meta lists ordinary payment reminders under [utility messages](https://whatsappbusiness.com/products/conversation-categories/utility/) but lists debt collection under [prohibited services](https://whatsappbusiness.com/policy/). Audio does not create an exemption. Confirm eligibility before adopting any real customer use case. Outside the actual 24-hour window, approved-template rules apply; this workflow does not attempt an audio-template workaround.
