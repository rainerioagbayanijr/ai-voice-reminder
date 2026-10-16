# Implementation verification — 15 October 2026

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

## Not claimed or verified

- No email was sent through an external SMTP account. Credentials were unavailable and unnecessary for local capture tests. Real provider authentication, inbox placement, spam handling, delivery, and playback remain unverified.
- Audio tone/pronunciation was not approved by a human listener. Generated samples are available for listening; byte/header checks do not establish perceptual quality.
- Edge speech's commercial authorization, enterprise privacy/retention commitments, and suitability for real financial-services data were not established by the successful technical calls. See `tts-and-compliance.md`.
- No real CRM, customer data, consent/suppression policy, production contact-hour enforcement, WhatsApp or Viber integration was used or implemented.
- No exactly-once inbox-delivery claim is made. Ambiguous SMTP attempts require reconciliation.

## Reproduce

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/e2e.py
.venv/Scripts/python.exe scripts/e2e.py --live
```

Use `TEST_DATABASE_URL` for the database tests as documented in `testing.md`; otherwise those tests skip. The local integration harness uses isolated test volumes and loopback ports and never relays SMTP. It leaves all schedules inactive. Generated secrets and capture artifacts are ignored by version control.
