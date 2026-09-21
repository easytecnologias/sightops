-- Baseline do banco principal (SQLite).
-- Espelha migrations/main/postgres/001_baseline.sql. Banco pre-existente adota
-- esta versao sem executar e e levado ate aqui pela 002.

CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tenant_slug, name)
);

CREATE TABLE IF NOT EXISTS settings_kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS json_state (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ip_cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    ip TEXT NOT NULL,
    host TEXT DEFAULT '',
    http_port INTEGER DEFAULT 80,
    title TEXT DEFAULT '',
    local TEXT DEFAULT '',
    status TEXT DEFAULT '',
    mac TEXT DEFAULT '',
    fabricante TEXT DEFAULT '',
    modelo TEXT DEFAULT '',
    snapshot_url TEXT DEFAULT '',
    imgbb_url TEXT DEFAULT '',
    raw_json TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tenant_slug, ip)
);

CREATE TABLE IF NOT EXISTS recorders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    host TEXT NOT NULL,
    http_port INTEGER NOT NULL DEFAULT 80,
    mac TEXT DEFAULT '',
    modelo TEXT DEFAULT '',
    fabricante TEXT DEFAULT '',
    local TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tenant_slug, source, host, http_port)
);

CREATE TABLE IF NOT EXISTS recorder_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    recorder_id INTEGER NOT NULL REFERENCES recorders(id) ON DELETE CASCADE,
    channel INTEGER NOT NULL,
    title TEXT DEFAULT '',
    status TEXT DEFAULT '',
    local TEXT DEFAULT '',
    camera_ip TEXT DEFAULT '',
    camera_mac TEXT DEFAULT '',
    camera_model TEXT DEFAULT '',
    snapshot_url TEXT DEFAULT '',
    imgbb_url TEXT DEFAULT '',
    raw_json TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(recorder_id, channel)
);
