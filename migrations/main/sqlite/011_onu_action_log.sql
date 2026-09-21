CREATE TABLE IF NOT EXISTS onu_action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_slug TEXT NOT NULL,
    olt_id INTEGER, olt_ip TEXT NOT NULL DEFAULT '', olt_name TEXT NOT NULL DEFAULT '', site TEXT NOT NULL DEFAULT '',
    pon TEXT NOT NULL DEFAULT '', onu TEXT NOT NULL DEFAULT '', serial TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL, ok INTEGER NOT NULL DEFAULT 1, detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS onu_action_log_tenant_olt_time_idx ON onu_action_log(tenant_slug, olt_ip, created_at DESC);
