# Test WhatsApp voice notes

WhatsApp now requests **OGG/Opus** from the existing speech endpoint and sends the uploaded media
using `type=audio` and `audio.voice=true`. Edge TTS still produces the speech; FFmpeg converts its
MP3 in memory to mono, 48 kHz, 32 kbps Opus in an OGG container. Email continues to use MP3.
The template, voice/language selection and customer personalization are shared.

Meta documents the voice flag and OGG/Opus requirement in its
[official audio reference](https://www.postman.com/meta/whatsapp-business-platform/request/juzqcg2/send-audio-message-by-url).
The recipient's WhatsApp client renders the message; confirm its voice-note appearance and playback
on your phone. Conversion or successful API submission alone does not establish receipt/playback.

## Run it yourself

1. Refresh n8n and open **WhatsApp Voice Reminder - Test Only**. The updated nodes are
   **Generate Voice Note**, **Voice Note Ready**, and **Upload Voice Note to Meta**.
2. Confirm the saved Header Auth credential on **Upload Voice Note to Meta** and **Send WhatsApp
   Audio** contains your current token. If expired, replace it privately in n8n; never paste it into
   chat or Demo Settings. Existing credential references are preserved during the local upgrade.
3. Send **Hello** from your verified phone to the Meta test sender. Enter the actual UTC time in
   Demo Settings `last_hello_at_utc`. Obtain the current UTC time immediately after Hello:

   ```powershell
   (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
   ```

4. Keep `routing_mode="test"`, `input_mode="csv"` and the matching configured test recipient.
   Set `mode="send"`, save, and execute the entire workflow from its trigger. The local workflow
   is prepared in send mode after its preview checks; a fresh JSON import defaults to preview.
5. With fresh unprocessed sample identities, four eligible CSV customers produce four personalized
   voice notes, all sent to your own verified phone. Three rows are skipped. Previously submitted
   reminders are skipped by the durable ledger; changing audio format does not bypass it.

For a no-send preview, set `mode="preview"`. Preview saves
`previews/whatsapp-<execution>-<customer>.ogg`; no Meta upload/send runs.
Old MP3 previews are historical and are not converted in place. Preview is repeatable and does not
consume a send identity. Native voice-note receipt requires the send-mode phone test above.

## Deployment and API

```powershell
docker compose up -d --build --wait tts-service
```

The API image installs FFmpeg; no extra service is added. Import the updated workflow JSON when
upgrading another deployment and select its existing Header Auth credential on both Meta nodes.
Keep the PostgreSQL volumes and stable institution/customer identities.
For standalone Python deployment outside Docker, install FFmpeg on the service's executable PATH.

- `POST /api/v1/voice/generate` returns MP3 (`audio/mpeg`), default and email behavior.
- `POST /api/v1/voice/generate?audio_format=ogg_opus` returns OGG/Opus (`audio/ogg`).
- The JSON request and `X-API-Key` authentication are unchanged.
- Converter timeout defaults to 10 seconds, with the configured audio-size limit and per-process
  concurrency limit. Children are killed/reaped on timeout/cancellation; no temporary files are made.
- Conversion errors return sanitized 502/503/504/429 responses. n8n treats them as preparation
  failures before upload/send, records `tts_failed`, and applies the existing bounded retry rules.
- The WhatsApp speech HTTP timeout is 70 seconds to cover the default 45-second speech deadline
  plus conversion. Adjust it if increasing backend speech/conversion timeouts.

See [tracking and recovery](whatsapp-reliability.md) for routing guards and held uncertain sends.
Inbound webhook setup, provider replacement and production hosting are separate work.
