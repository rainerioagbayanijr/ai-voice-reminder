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

-- Separate channel tables preserve the existing email ledger and its constraints.
CREATE TABLE IF NOT EXISTS whatsapp_reminders (
    reminder_id text PRIMARY KEY,
    customer_id text NOT NULL,
    institution_id text NOT NULL,
    due_date date NOT NULL,
    routing_mode text NOT NULL CHECK (routing_mode IN ('test','customer')),
    status text NOT NULL CHECK (status IN
        ('processing','submitting','submitted','failed','rejected','unknown')),
    attempt_count integer NOT NULL DEFAULT 0,
    token uuid NOT NULL,
    recipient_fingerprint text NOT NULL,
    phone_number_id text NOT NULL,
    window_expires_at timestamptz NOT NULL,
    lease_until timestamptz,
    retry_after timestamptz,
    message_id text,
    submitted_at timestamptz,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS whatsapp_events (
    event_id bigserial PRIMARY KEY,
    reminder_id text NOT NULL REFERENCES whatsapp_reminders(reminder_id),
    status text NOT NULL,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS whatsapp_events_reminder_idx ON whatsapp_events(reminder_id);

-- No message bodies, profile names, raw payloads or phone numbers are retained.
CREATE TABLE IF NOT EXISTS whatsapp_inbound_events (
    tenant_id text NOT NULL,
    phone_number_id text NOT NULL,
    message_id text NOT NULL,
    recipient_fingerprint text NOT NULL,
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, phone_number_id, message_id)
);
CREATE INDEX IF NOT EXISTS whatsapp_inbound_window_idx ON whatsapp_inbound_events
    (tenant_id, phone_number_id, recipient_fingerprint, occurred_at DESC);
CREATE TABLE IF NOT EXISTS whatsapp_delivery_events (
    tenant_id text NOT NULL,
    phone_number_id text NOT NULL,
    message_id text NOT NULL,
    recipient_fingerprint text NOT NULL,
    status text NOT NULL CHECK (status IN ('sent','delivered','read','failed')),
    occurred_at timestamptz NOT NULL,
    error_code integer,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, phone_number_id, message_id, status, occurred_at)
);
