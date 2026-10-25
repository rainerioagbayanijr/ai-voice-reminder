# Implementation verification

## Replaceable speech providers on 24 October 2026

- Added the `SpeechProvider` protocol, a provider factory, Edge and optional ElevenLabs adapters,
  and a shared service for rendering, deadlines, concurrency and MP3 validation. OGG conversion and
  n8n delivery use the same contract. There is no automatic provider failover.
- **167 tests with PostgreSQL and all 20 actual n8n integration scenarios passed.** The final
  logging change passed an additional focused rerun of 76 affected tests. Ruff and whitespace
  checks passed; no live credentials were added to source.
- Both mocked provider paths passed real MP3/Opus codec checks in a network-disabled container.
  A real deployed Edge preview also produced valid MP3 and OGG/Opus recordings using the existing
  Filipino voice. The local stack remains configured for Edge, not the paid provider.
- Live ElevenLabs synthesis/account validation is intentionally unverified without credentials.
  The n8n workflow and Meta credential references were not changed. No live WhatsApp message or
  email was sent during these checks. See `speech-providers.md` and `testing.md` for details.

## Native voice notes on 24 October 2026

- Added bounded in-memory FFmpeg conversion for `audio_format=ogg_opus`. WhatsApp uses
  `payment_reminder.ogg`, uploads `audio/ogg`, and reserves `audio:{id,voice:true}`. Email keeps MP3.
- **139 automated tests and 20 actual n8n integration scenarios passed**, with real PostgreSQL
  and FFmpeg. Local provider mocks verified upload bytes, Opus metadata and the voice flag.
- A real local Edge TTS CSV preview generated four distinct OGG/Opus recordings and skipped three
  rows. ffprobe and full decoding verified all four. No upload/send node executed in that preview.
- The upgraded workflow is imported locally with its credentials preserved and manual settings
  prepared for CSV/test/send. Customer routing remains disabled. No live Meta send was performed;
  current credentials and an actual recent incoming-message timestamp are required for the phone test.
- Source workflow defaults remain preview. Speech wording and the durable reminder identity are
  unchanged, so switching audio format does not bypass duplicate protection.
- See `whatsapp-voice-notes.md` for the user's next steps; `testing.md` records the measured scope.

## Earlier WhatsApp reliability upgrade on 24 October 2026

- Added separate durable PostgreSQL tracking for WhatsApp: atomic claims, single-use reservations,
  persistent message IDs/events, processing-lease recovery, bounded preparation retries and held
  uncertain/rejected submissions.
- Added backend-enforced test recipient matching and an explicitly enabled customer-routing path.
  Customer mode uses each CSV row's phone and incoming-message timestamp; it stays disabled locally.
- **126 automated tests passed with real PostgreSQL and no database skips. All 19 actual n8n
  integration scenarios passed** with local provider mocks. See `testing.md` for measured scope.
- Existing script, MP3 audio format, Edge TTS provider and email delivery behavior are retained.
  A real local Edge TTS CSV preview generated four distinct MP3s and skipped three rows, with
  zero upload/send attempts and no failures. Live Meta delivery with the current account/token
  was not revalidated. The upgraded local workflow is imported in preview/test mode with its
  existing credential references preserved; API, n8n and PostgreSQL are healthy.
- The pre-upgrade WhatsApp workflow did not record durable send history. Its historical sends cannot
  be automatically deduplicated by this new ledger. Review before the first post-upgrade send.
- Webhook verification, native voice-note format and production hosting remain separate work.

## Historical prototype status on 16 October 2026

- The WhatsApp test workflow now reads the seven-row fictional CSV and generates separate recordings for Juan, Maria, Ana and Luis. One invalid row, one ineligible row and one duplicate are skipped. All sends use the configured verified test phone; CSV phone numbers are ignored.
- The final opening uses Rain from Test Company and Test Bank, with a sentence pause between the company and bank. Filipino speech dates are written as explicit English words; email dates retain English month names and digits.
- The final wording passed the 81-test suite and Ruff. Twelve database integration tests were explicitly skipped because no test database URL was supplied; the original database checks below remain historical evidence.
- Nine isolated n8n scenarios passed during CSV integration. A subsequent live Edge TTS preview with the final wording produced four MP3s and skipped three rows without sending messages.
- Live receipt in WhatsApp was confirmed during the earlier single-customer demonstration. Current CSV preview checks do not establish inbox delivery or playback for every later execution. See `testing.md` and `whatsapp-test.md` for the measured scope and operator steps.

## Initial email MVP verification on 15 October 2026

The following results describe the original five-row email test fixture and deployment at that time. Later CSV additions, Filipino templates and WhatsApp work are summarized above.

## Passed

- Docker image built successfully with Python 3.12. The n8n 2.43.6, API, PostgreSQL and test SMTP capture containers became healthy. The final PostgreSQL pin is 17.11, verified from published image tags; the 50-test suite was also rerun successfully after upgrading the test database to 17.11.
- **50 automated Python tests passed**, including tests against a real local PostgreSQL instance. Local test interpreter: Python 3.13.3. One upstream Starlette warning recommends its newer test-client transport; tests passed with the pinned httpx version.
- Ruff checks passed for `app`, `scripts` and `tests`.
- Real `edge-tts` 7.3.1 calls generated two different MP3 recordings: Juan, 135,648 bytes; Maria, 136,080 bytes. The smoke check verified an MP3 header and nontrivial output size. Files: `previews/smoke-juan.mp3`, `previews/smoke-maria.mp3` (ignored generated artifacts).
- The actual workflow JSON imported into n8n 2.43.6. Both the credential-selected test export and the original export with no SMTP credential imported successfully. The original export executed successfully in dry-run configuration without selecting an SMTP credential.
- The five-row CSV was read and parsed by the actual n8n file/CSV nodes. Two eligible customers were independently processed, one invalid and one ineligible record were skipped, and the repeated customer was suppressed.
- **Actual workflow + real online speech + local SMTP capture passed:** each customer produced a distinct nontrivial recording; each SMTP submission had one `payment_reminder.mp3` file attachment; all recipients were `capture@example.com`; two `sent` records were stored. Whole-workflow reruns produced no additional submissions.
- **Actual workflow dry run + real online speech passed:** two MP3 files were saved, statuses were `dry_run`, and no SMTP submissions occurred. A rerun did not generate duplicate completed reminders.
- The mock-boundary integration harness passed SMTP rejection and lost-acknowledgement scenarios. Both recorded `unknown` and suppressed retries. The lost-acknowledgement scenario captured messages before dropping the connection, demonstrating the duplicate risk that quarantine avoids.
- Mocked provider failure exhausted n8n's bounded TTS retries, recorded `failed`, and respected backoff on a repeated execution. After test-only advancement of the retry clock and provider recovery, both reminders were submitted with `attempt_count=2`.
- Eight concurrent PostgreSQL claim calls yielded one owner; tests verified expired lease recovery, stale-worker fencing, invalid state rejection, terminal acknowledgement replay, and separate dry-run/email identities.
- The final **normal three-service Compose deployment** (without test overrides) was rebuilt and started healthy on PostgreSQL 17.11. Its original workflow was imported without SMTP credentials and executed successfully through `Complete`: two real MP3 previews (135,648 and 135,936 bytes), two skipped records, and the duplicate suppressed. The normal stack was left running at localhost ports 5678 and 8000 with `DRY_RUN=true`, generated ignored local secrets, and an inactive schedule. The isolated test stack was stopped; its volumes were preserved.

## Initial verification limits and continuing boundaries

- At the initial verification, no email was sent through an external SMTP account; credentials were unavailable and unnecessary for local capture tests. A later controlled Ethereal test obtained one accepted SMTP submission, while ambiguous attempts were quarantined. SMTP acceptance still does not establish inbox placement, spam handling, delivery or playback.
- Audio tone/pronunciation was not approved by a human listener. Generated samples are available for listening; byte/header checks do not establish perceptual quality.
- Edge speech's commercial authorization, enterprise privacy/retention commitments, and suitability for real financial-services data were not established by the successful technical calls. See `tts-and-compliance.md`.
- No real CRM, customer data, consent/suppression policy, production contact-hour enforcement or Viber integration was used or implemented. WhatsApp was added later as the owner-only test workflow summarized above.
- No exactly-once inbox-delivery claim is made. Ambiguous SMTP attempts require reconciliation.

## Reproduce

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/e2e.py
.venv/Scripts/python.exe scripts/e2e.py --live
```

Use `TEST_DATABASE_URL` for the database tests as documented in `testing.md`; otherwise those tests skip. The local integration harness uses isolated test volumes and loopback ports and never relays SMTP. It leaves all schedules inactive. Generated secrets and capture artifacts are ignored by version control.
# Milestone 6 — 2026-10-25

Built the optional isolated webhook gateway and Cloudflare Quick Tunnel profile.
182 automated tests and 20 actual n8n regression scenarios passed. PostgreSQL
ingestion/window/history integration and FFmpeg use real local implementations;
the regression harness mocks external speech/Meta. No actual messages were sent.
The live HTTPS token challenge and private-route isolation passed. All five normal
services are healthy. Existing n8n Demo Settings and Meta credential references
were preserved during import; manual window mode remains selected until Meta setup.

After the operator saved the App Secret, the gateway was recreated and all public
callback checks passed again: valid locally signed notification accepted, invalid
signature rejected, token challenge verified, and private routes blocked. No Hello
event or outbound message was created by this smoke test. Real incoming Meta
Hello/delivery notifications are **not yet verified**; configure the Meta callback
and messages subscription, then enable webhook window mode after a real incoming
message is recorded. The tunnel hostname is temporary.
See [setup and code-review guide](whatsapp-webhooks.md).
