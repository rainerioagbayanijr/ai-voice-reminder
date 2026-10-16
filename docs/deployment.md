# Deployment and recovery

## Containers and credentials

The normal Compose stack has three services: n8n 2.43.6, Python 3.12 FastAPI, and PostgreSQL 17.11. PostgreSQL is internal only. API and n8n ports bind to loopback. The API runs as UID 10001, with a read-only root filesystem and no Linux capabilities. The MP3 is returned in memory, so no writable temporary directory is required. n8n uses its named volume for credentials, settings, workflow storage, and transient binary data. PostgreSQL has its own volume. Back up both volumes and the n8n encryption key together.

Copy `.env.example` to `.env`; generate unique hexadecimal secrets and replace the placeholders. API configuration is read at startup. Run `docker compose up -d --build --wait`. After editing templates or Python code, rebuild; after environment changes, `docker compose up -d --wait` recreates the affected service. `docker compose restart` alone does not apply changed environment values.

The CSV is mounted read-only at `/files/input/customers.csv`. Dry-run previews are written to `/files/previews`, mapped to the host's `previews` directory. On Linux, create that directory and grant UID 1000 write access (for example, `sudo chown 1000:1000 previews`). Avoid world-writable permissions. Windows Docker Desktop uses host-shared directory permissions.

n8n must be able to read the API key in expressions. This local single-owner configuration explicitly sets `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`. Any n8n workflow editor is therefore trusted with container environment secrets. Do not invite untrusted editors. For shared deployment, replace expression-based headers with a restricted n8n Header Auth credential, enable environment access blocking, and remove the API key from n8n's environment. SMTP credentials are selected manually and stored encrypted by n8n. The export contains no actual credential values.

Create the owner account at first start. Import `workflows/payment_reminder.json` via the UI, select SMTP credentials for email testing, and keep the workflow inactive until its trigger should run. The CLI import is also supported:

```powershell
docker compose exec n8n n8n import:workflow --input=/workflows/payment_reminder.json
```

The daily trigger uses 09:00 Asia/Manila. Import does not activate/publish the schedule. The MVP does not enforce recipient-specific contact windows, opt-outs, current balance/payment status, or a due-date horizon. These must be added before real deployment. A missing or unreadable CSV aborts that execution; invalid row values are individually recorded/skipped. Structurally malformed CSV is a batch input failure to correct at source.

## Monitoring

`/health` checks API process liveness; `/ready` also checks PostgreSQL. Provider/network/SMTP availability is established during each actual attempt, not by readiness. n8n `/healthz` checks process health. Inspect `docker compose ps` and sanitized API JSON logs. n8n error/manual/success payload persistence is disabled to reduce exposure; operators can still view live manual execution data. PostgreSQL is the durable message history. Transient n8n binaries are pruned under its execution retention settings; review retained files during operations.

Use the authenticated `GET /api/v1/reminders` endpoint for recent status. For event detail:

```powershell
docker compose exec postgres psql -U reminder -d reminders -c "SELECT reminder_id,status,reason,created_at FROM reminder_events ORDER BY event_id DESC LIMIT 30;"
```

`sent_at` is server-side SMTP submission acknowledgement time, not delivery time. Error messages are fixed codes; private provider exceptions, names, addresses, scripts, tokens and recordings are omitted from application logs. The API still needs the customer name/institution/date in memory to synthesize speech.

## Retry and crash recovery

Run the entire workflow again from the trigger. Preparation failures become eligible after five minutes, subject to the three-claim limit. A crashed preparation becomes eligible after its ten-minute lease expires. The HTTP request node retries TTS three times before marking the claim failed. Expected total TTS time (three 55-second HTTP deadlines and two five-second pauses) fits within the default lease. If tuning these values, keep the lease longer than preparation and do not exceed the one-hour workflow execution deadline.

Never enable retry-on-failure on **Send Test Email** or **Reserve SMTP Submission**. Never retry a failed execution from a cached middle node. Rerun from the manual/schedule trigger so claim ownership is checked. A reservation is deliberately consumed once.

`submitting`/`unknown` require operator investigation:

1. Pause the workflow and confirm the worker that owned the claim is stopped.
2. Check SMTP provider logs, the controlled inbox, and local audit history. Establish whether the message was accepted; an empty inbox alone is insufficient evidence.
3. If submission is proven accepted, an operator may reconcile `sent` with an audited note. If non-submission is proven, a separately audited administrative action can reset it to retryable `failed`. This MVP intentionally exposes no automatic reset endpoint. Do not reset ambiguous attempts.
4. Preserve the original reminder and event history and record the evidence, operator, and decision in an operational audit system. Start a complete new execution only after reconciliation.

An interrupted `submitting` row may mean no email was ever attempted. That is the acknowledged cost of duplicate prevention with SMTP. Exactly-once delivery is not promised.

## Troubleshooting

| Symptom | Action |
|---|---|
| Docker pipe/socket unavailable | Start Docker Desktop/Engine and select Linux containers |
| API 401 | Confirm the same API key reaches API and n8n; recreate after changes |
| API fails on startup with recipient validation | Keep dry run enabled or verify and configure a single owned test inbox |
| Missing SMTP credential | Select a valid SMTP credential on Send Test Email; no credential export ships |
| TTS 502/504 or 403 upstream | Check HTTPS/WebSocket egress, DNS, certificates and current edge-tts compatibility; retries are bounded |
| API 429 | Reduce simultaneous executions or increase tested per-process limits |
| No file access / permission denied | Check mounts, `/files` allowlist and host directory permissions |
| 409 status update | Stale token, lease expiry, invalid transition or attempted reservation replay; investigate and start at trigger |
| No new email on rerun | Check existing reminder identity, mode, backoff, attempt limit and quarantined status |
| n8n warns Python runner missing | Workflow uses JavaScript only; the optional Python runner is not required |

For deployment beyond loopback, configure TLS, secure cookies, network access controls, credential isolation, secret rotation, volume encryption/backups, resource sizing, and upgrades with verified compatible workflow nodes. Do not expose the test SMTP sink. Before changing pinned dependencies, rerun the test suite and n8n integration harness.

Stop the test stack without deleting volumes:

```powershell
docker compose -p reminder-test --env-file .verification/test.env -f docker-compose.yml -f docker-compose.test.yml down
```
