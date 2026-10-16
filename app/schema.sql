CREATE TABLE IF NOT EXISTS reminders (
    reminder_id text PRIMARY KEY,
    customer_id text,
    due_date date,
    channel text NOT NULL DEFAULT 'email' CHECK (channel = 'email'),
    mode text NOT NULL CHECK (mode IN ('dry_run', 'test_email')),
    status text NOT NULL CHECK (status IN
        ('pending','processing','submitting','sent','failed','skipped','unknown','dry_run')),
    attempt_count integer NOT NULL DEFAULT 0,
    token uuid,
    lease_until timestamptz,
    retry_after timestamptz,
    sent_at timestamptz,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS reminder_events (
    event_id bigserial PRIMARY KEY,
    reminder_id text NOT NULL REFERENCES reminders(reminder_id),
    status text NOT NULL,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reminder_events_reminder_idx ON reminder_events(reminder_id);
