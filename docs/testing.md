# Verification and reproducible tests

## Replaceable speech providers — 24 October 2026

- **167 automated tests passed against PostgreSQL with no database skips.** New provider tests
  verify selection, fail-closed configuration, voice allowlists, speed/volume rules, authentication,
  payload/output format, redirects, stream-size limits, deadlines/cancellation and secret-safe errors.
  After adding sanitized provider-status logging, all 76 affected service/API tests passed again.
- **All 20 n8n integration scenarios passed** after the refactor, using real PostgreSQL/FFmpeg and
  local speech/Meta fixtures. Existing routing, tracking, retry and voice-note contracts are retained.
- A container with **networking disabled** tested both provider paths using a local tone: Edge's
  options with a mocked synthesis function, and the actual ElevenLabs adapter with a mocked HTTP
  session. Both returned MP3 through the shared service and valid mono 48 kHz OGG/Opus through the
  real converter. ffprobe and full decoding passed. No paid/provider network request was made.
- The deployed Edge adapter also generated real Filipino MP3 and OGG/Opus previews. Both decoded
  fully: MP3 182,736 bytes (24 kHz mono), OGG 114,589 bytes (48 kHz mono Opus). No Meta request ran.
- Edge remains selected. The n8n workflow, Meta credentials, script and reminder identities were
  not edited for this provider upgrade. Live ElevenLabs credentials, account/model access, supported
  languages and acoustic quality remain unverified. One upstream test-client warning remains.

See [speech-provider configuration](speech-providers.md) for setup and repeatable codec checks.

## Native voice-note upgrade — 24 October 2026

- **139 automated tests passed with PostgreSQL, no database skips.** Additional tests cover
  conversion capacity, timeout/child cleanup, byte limits, invalid output, missing FFmpeg,
  sanitized HTTP failures, format selection and MP3 backward compatibility. Ruff passed.
- **20 actual n8n scenarios passed** with the real FastAPI/FFmpeg converter, real PostgreSQL,
  and local tone/Meta mocks. ffprobe verified uploaded `audio/ogg` files as mono 48 kHz Opus;
  payload assertions verified `audio.voice=true`. Conversion failures stopped before upload/send.
  Duplicate protection, restart recovery, backoff and uncertain-send quarantine also passed.
- A **real Edge TTS preview** in the local n8n instance (execution 24) generated four distinct
  spoken `.ogg` files for Juan, Maria, Ana and Luis and skipped three rows. All four decoded
  fully without errors and were verified as mono 48 kHz Opus. No Meta upload/send node ran.
- The updated API image built successfully with FFmpeg. The local API, n8n and PostgreSQL are healthy.
- The manual local workflow is prepared as **CSV + test routing + send mode** for the user's
  next phone test. Public JSON still defaults to preview. Existing credential references and
  the test recipient are preserved; customer routing remains disabled.
- **Live Meta acceptance, phone rendering and playback remain unverified for this format.**
  The saved Hello timestamp needs refreshing, and the operator must ensure the token is current.
  No live WhatsApp message or email was sent during this verification. One upstream
  Starlette/httpx deprecation warning remains; no test failure.

Follow [voice-note test steps](whatsapp-voice-notes.md) before executing send mode.

## Earlier WhatsApp reliability upgrade — 24 October 2026

- **126 tests passed, no database skips**, against fresh disposable PostgreSQL 17.11, including
  concurrent claims, backend-store restart, leases, stale tokens, recipient binding, customer/test
  separation, backoff, retry limits and unknown-send protection. Ruff and whitespace checks passed.
- **19 actual n8n 2.43.6 scenarios passed**, using real FastAPI/PostgreSQL tracking and mocked
  speech/Meta providers. These verified CSV test routing, distinct customer routing, duplicate
  reruns after API-container restart, recovery from TTS failure and explicit throttling, rejected
  submissions and a lost acknowledgement that stays blocked on rerun.
- Tests also inspect the durable status after each send-mode execution. Fixture audio proves
  transport only. No live Meta message or SMTP email was sent by this verification.
- The rebuilt local API became healthy, created the additional WhatsApp tables, and retained the
  existing email ledger. Customer routing remains disabled; the updated workflow defaults to preview.
- The updated local workflow also passed a real Edge TTS preview: execution 23 generated four
  distinct, nonempty MP3s with valid headers for Juan, Maria, Ana and Luis, skipped three rows,
  and executed no upload/send nodes. No failures were reported. This is not a listening-quality test.
- One upstream Starlette/httpx test-client deprecation warning remains; no test failure.

Run `.venv/Scripts/python.exe scripts/test_whatsapp_e2e.py` after installing development dependencies.
It provisions its own database, runs pytest, executes the workflow scenarios and cleans up its
containers/networks. See [tracking and routing details](whatsapp-reliability.md).

## Automated Python tests

Install `requirements-dev.txt` in a Python 3.12+ virtual environment and run `python -m pytest -q`. Tests mock the online Edge boundary, validate binary API responses, authentication, required/invalid fields, safe logs/errors, templates, prosody, capacity, deadline, empty output and size limits. Workflow tests verify binary attachment contracts and safe retry configuration; they are not substitutes for importing/running in n8n.

Database tests use real PostgreSQL transactions and thread concurrency. They cover eight simultaneous claims, successful/failed states, retry delay/limit, stale leases/tokens, uncertain email submission, terminal acknowledgement replay and separate dry-run identities. Set `TEST_DATABASE_URL` to a disposable database. Tests namespace their identities and remove only their own records; never point test tooling at production.

After starting the integration stack with `scripts/e2e.py`, a PowerShell database test command is:

```powershell
$testConfig = Get-Content .verification/test.env | ConvertFrom-StringData
$env:TEST_DATABASE_URL = 'postgresql://reminder:' + $testConfig.POSTGRES_PASSWORD + '@127.0.0.1:55432/reminders'
.venv/Scripts/python.exe -m pytest -q --basetemp=.verification/pytest-temp
```

With no database URL, integration tests are marked skipped, not counted as passed. On Windows, the sandbox may need local socket access for asyncio and FastAPI TestClient. Use a workspace-local `--basetemp` if the system temporary directory is restricted.

## Full n8n integration harness

`python scripts/e2e.py` starts the isolated `reminder-test` Compose project, builds the API, imports SMTP credentials for a local non-relaying capture sink, and imports the actual workflow export. The only provider mock is the Edge adapter. Fixture bytes are deliberately not playable speech; they prove exact personalization and binary routing, not acoustic quality.

Scenarios check all five CSV rows, invalid/ineligible skips, separate customer attachments, exact test-recipient routing, persistent status, duplicate reruns, saved dry-run previews, SMTP rejection, lost SMTP acknowledgement, TTS failure, backoff, and successful retry after recovery. The test sink never forwards email. It has no authentication or TLS because it is confined to the local test network; its HTTP inspection port binds to loopback. It is not part of the normal deployment.

`python scripts/e2e.py --live` uses the real online Edge adapter for both email-capture and dry-run paths. It checks nonempty distinct recordings and captures the attachments through the actual n8n SMTP node. `python scripts/tts_smoke.py` also creates two fictional MP3s without any email step. These commands need internet and may fail when the unofficial upstream service changes or is unavailable. Live tests are not silently substituted with mocks.

The harness keeps test volumes for inspection and leaves schedules inactive. Stop it with the command in `docs/deployment.md` before starting the ordinary Compose stack. No real SMTP account or inbox delivery is tested by the harness. A final controlled-inbox test and human review of the recordings remain operator acceptance steps.

## Results from this implementation session

See `verification.md` for the final measured results and remaining external acceptance checks.

### Filipino configuration verified on 16 October 2026

The updated suite passed 66 tests; 12 database integration tests were skipped because no `TEST_DATABASE_URL` was provided. Ruff passed. New checks cover all three Filipino templates, representative Filipino month names, placeholder substitution, and selection of `fil-PH-BlessicaNeural` with a mocked speech dependency.

The running Compose service was rebuilt with `LANGUAGE=fil` and `VOICE=fil-PH-BlessicaNeural`. A real authenticated API request using fictional details returned HTTP 200, `audio/mpeg`, and a 176,832-byte MP3 saved as an ignored local preview. All normal containers were healthy afterward. No email or WhatsApp message was sent for this language verification; pronunciation and tone require listening review.

### English speech dates and WhatsApp CSV mode

After feedback that numeric dates were still spoken in Filipino, Filipino voice templates were changed to use explicit English words, such as `November fifteenth, two thousand twenty-six`. Email dates remain `November 15, 2026`. A live script-preview request confirmed the exact rendered wording and the Rain from AMG / ABC Bank introduction. Listening review remains necessary; string and transport tests do not establish acoustic quality.

The updated suite passed 81 tests; 12 database tests were skipped because no test database URL was supplied. Ruff passed. Nine actual-n8n scenarios passed against a local mock on a Docker network without internet, including a two-customer CSV preview and send batch. The CSV cases verified different names/dates, the configured agent/bank override, distinct preview filenames, one fixed test destination, and invalid/ineligible/duplicate skips. Existing upload/send failure and ambiguous acknowledgement cases still passed.

The normal n8n workflow then processed the real seven-row mock CSV in preview mode using live Edge TTS. It produced four separate MP3s for Juan, Maria, Ana and Luis, and skipped three rows. No WhatsApp send node ran during that preview. The API and normal containers were healthy. Local audio and credentials remain ignored by Git.

### Final company and bank wording

After listening feedback on acronyms, the final demo values became `agent_name=Rain from Test Company` and `bank_name=Test Bank`. The template now puts a full stop after the agency introduction: `Hi, this is Rain from Test Company. Calling from Test Bank, ...`. Customer names still come from CSV and speech dates remain English words.

The full suite passed 81 tests, with 12 database tests skipped; Ruff passed. A fresh actual-n8n CSV preview with these values completed with four nonempty MP3 files and three skipped rows. The script-preview endpoint confirmed the exact opening. Send mode was restored afterward with the other settings and credential references preserved. These checks did not send WhatsApp messages or claim independent acoustic approval.
# Milestone 6 verification — 2026-10-25

- Full suite: **182 passed**, with a disposable PostgreSQL database; no skipped tests.
- Actual n8n regression harness: **20 scenarios passed** with real FastAPI,
  PostgreSQL and FFmpeg, mocked speech/Meta boundaries, and no real sends.
- Webhook coverage includes raw-body signatures, token verification, size limits,
  database failures, concurrent duplicates, expired/foreign-recipient windows,
  invalid-event transaction rollback, late/out-of-order receipts, and signed HTTP
  ingestion opening a private API claim without a manually supplied timestamp.
- Live temporary HTTPS tunnel: correct token returns plain challenge; wrong token
  returns 403; docs/private history routes return 404. After the App Secret was
  saved and the gateway recreated, a locally signed notification returned 200 and
  an invalid signature returned 401. Real Meta-originated notifications remain
  pending dashboard setup and a fresh incoming message.
- All five running Compose services are healthy. Ruff, Compose validation and
  `git diff --check` pass. One existing Starlette/httpx deprecation warning remains.

Run `python scripts/check_webhook_tunnel.py` after saving the App Secret and
recreating the gateway. It checks public ingress without creating a Hello event
or sending a WhatsApp message. See [Meta setup](whatsapp-webhooks.md).
