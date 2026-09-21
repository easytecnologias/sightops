CREATE TABLE IF NOT EXISTS onu_signal_samples (
    id BIGSERIAL PRIMARY KEY, tenant_slug TEXT NOT NULL, entity_key TEXT NOT NULL,
    onu_rx DOUBLE PRECISION, olt_rx DOUBLE PRECISION, distance_km DOUBLE PRECISION,
    oper_status TEXT NOT NULL DEFAULT '', omci_status TEXT NOT NULL DEFAULT '', captured_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS onu_signal_samples_entity_time_idx ON onu_signal_samples(tenant_slug, entity_key, captured_at DESC);
CREATE TABLE IF NOT EXISTS notification_states (
    id BIGSERIAL PRIMARY KEY, tenant_slug TEXT NOT NULL, entity_key TEXT NOT NULL, alert_kind TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0, opened_at TIMESTAMPTZ, closed_at TIMESTAMPTZ, last_sent_at TIMESTAMPTZ,
    last_value TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS notification_states_tenant_entity_kind_uq ON notification_states(tenant_slug, entity_key, alert_kind);
