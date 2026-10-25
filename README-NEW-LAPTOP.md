# New laptop: WhatsApp demo

Use the same Meta app, supplied test sender, and verified personal recipient.
This demo uses manual timestamps; no webhook, tunnel, publishing, SMTP, or webhook
Verify token is needed. Use fictional customers and test routing only.

## 1. Start the app (first time)

Install Git, Python 3.12+, and Docker Desktop. Start Docker with Linux containers.
In PowerShell:

```powershell
git clone https://github.com/rainerioagbayanijr/ai-voice-reminder.git
cd ai-voice-reminder
python scripts/setup_env.py
```

Edit the generated `.env`:

```dotenv
WHATSAPP_TEST_RECIPIENT=YOUR_VERIFIED_PHONE_WITH_COUNTRY_CODE
WHATSAPP_TEST_RECIPIENT_VERIFIED=true
WHATSAPP_WINDOW_SOURCE=manual
```

Use digits only for the phone, with no spaces. Keep customer routing disabled.
Then run:

```powershell
docker compose up -d --build --wait
```

Open http://localhost:5678, create the local n8n owner account, and import
`workflows/whatsapp_voice_test.json` using **Import from File**.

## 2. Configure the WhatsApp test

Open your existing app at https://developers.facebook.com/apps/ → WhatsApp →
**Step 1: Try it out** (or API Testing/API Setup). Generate/copy the **Access token**.
The temporary token normally expires after 24 hours; generate another when expired.

In n8n, open **Upload Voice Note to Meta** and create a **Header Auth** credential:

- Name: `Authorization`
- Value: `Bearer YOUR_ACCESS_TOKEN` (one space after Bearer).

Select this same saved credential in **Send WhatsApp Audio**. Update the shared
credential only once when replacing an expired token. This access token is
different from the App Secret and webhook Verify token. Keep all secrets private.

In **Demo Settings**, set:

- `input_mode`: `csv`
- `routing_mode`: `test`
- `window_source`: `manual`
- `test_recipient`: the same verified personal phone as `.env`
- `phone_number_id`: the sender's **Phone Number ID** from Meta (not your phone)
- `graph_api_version`: the version shown in Meta's sample API request
- `meta_test_number_confirmed`: `true`, after confirming Meta's supplied test sender
- `recipient_verified`: `true`, after verifying/allowlisting your personal phone in Meta

Keep `institution_id` unchanged. Start with `mode=preview` to generate `.ogg` files
in `previews/` without sending; change to `mode=send` for the phone test.

## 3. Run the phone demo

1. Send **Hello from your verified personal WhatsApp phone to Meta's test sender**.
2. Immediately run this in PowerShell:

   ```powershell
   (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
   ```

3. Paste the result into **Demo Settings → `last_hello_at_utc`** and save.
4. Execute the **whole workflow** from its manual trigger.
5. Receive and play the personalized voice notes on your test phone.

Each eligible CSV customer produces a separate recording, all redirected to your
configured test phone. Submitted reminders are skipped on later runs. To test a
new reminder, append a fictional row with an unused customer ID to
`data/customers.csv`, save, and execute again. CSV edits need no Docker restart.
Reuse the Hello timestamp while its 24-hour window remains open; otherwise send
a fresh Hello and update it. Renewing an access token does not renew this window.

## Next time

Start Docker Desktop, open the project folder, and run `docker compose up -d --wait`.
Open n8n, refresh an expired access token if needed, and follow the phone-demo steps.
Git does not transfer `.env`, saved n8n credentials/settings, or database history.
A fresh laptop database can send all eligible rows again; run only the intended
test instance. Stop with `docker compose stop` to preserve local data.
