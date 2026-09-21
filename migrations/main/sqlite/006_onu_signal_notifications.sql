CREATE TABLE IF NOT EXISTS onu_signal_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_slug TEXT NOT NULL, entity_key TEXT NOT NULL,
    onu_rx REAL, olt_rx REAL, distance_km REAL, oper_status TEXT NOT NULL DEFAULT '', omci_status TEXT NOT NULL DEFAULT '',
    captured_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS onu_signal_samples_entity_time_idx ON onu_signal_samples(tenant_slug, entity_key, captured_at DESC);
CREATE TABLE IF NOT EXISTS notification_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_slug TEXT NOT NULL, entity_key TEXT NOT NULL, alert_kind TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0, opened_at TEXT, closed_at TEXT, last_sent_at TEXT, last_value TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS notification_states_tenant_entity_kind_uq ON notification_states(tenant_slug, entity_key, alert_kind);
