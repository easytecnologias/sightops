-- Cadastro de OLT (SQLite). Espelha migrations/main/postgres/003_olt_registry.sql.
--
-- Ver o arquivo do Postgres para o porque de vendor e model separados e de
-- password_enc guardar apenas texto cifrado (app/core/crypto.py).

CREATE TABLE IF NOT EXISTS olts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    vendor TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    password_enc TEXT NOT NULL DEFAULT '',
    connector_id TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS olts_tenant_slug_host_uq
    ON olts(tenant_slug, host);

CREATE INDEX IF NOT EXISTS olts_tenant_slug_idx
    ON olts(tenant_slug);
