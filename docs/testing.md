# Verification and reproducible tests

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
