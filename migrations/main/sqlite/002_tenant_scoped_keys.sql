-- Leva um banco pre-existente ate a forma da baseline 001.
--
-- SQLite nao tem ALTER TABLE DROP CONSTRAINT, entao a unica forma de trocar
-- UNIQUE(ip) por UNIQUE(tenant_slug, ip) e recriar a tabela e copiar os dados.
--
-- O SELECT abaixo le so as colunas que existem tanto no schema antigo quanto na
-- baseline (ou seja, todas menos tenant_slug), o que faz este arquivo rodar sem
-- erro nos dois casos. Num banco criado pela 001 as tabelas estao vazias e a
-- copia e inofensiva; num banco que ja tem tenant_slug preenchido esta migration
-- nem chega a rodar (a pos-condicao carimba a versao -- ver db_store.py).

-- foreign_keys e desligado pelo runner antes da transacao (PRAGMA dentro de
-- transacao e ignorado) e religado depois, com foreign_key_check no final.

CREATE TABLE sites_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tenant_slug, name)
);
INSERT OR IGNORE INTO sites_new(id, tenant_slug, name, description, active, created_at)
    SELECT id, 'default', name, COALESCE(description, ''), COALESCE(active, 1),
           COALESCE(created_at, datetime('now'))
    FROM sites;

CREATE TABLE ip_cameras_new (
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
INSERT OR IGNORE INTO ip_cameras_new(
    id, tenant_slug, site_id, ip, host, http_port, title, local, status, mac,
    fabricante, modelo, snapshot_url, imgbb_url, raw_json, updated_at
)
    SELECT id, 'default', site_id, ip, COALESCE(host, ''), COALESCE(http_port, 80),
           COALESCE(title, ''), COALESCE(local, ''), COALESCE(status, ''), COALESCE(mac, ''),
           COALESCE(fabricante, ''), COALESCE(modelo, ''), COALESCE(snapshot_url, ''),
           COALESCE(imgbb_url, ''), COALESCE(raw_json, ''), COALESCE(updated_at, datetime('now'))
    FROM ip_cameras;

CREATE TABLE recorders_new (
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
INSERT OR IGNORE INTO recorders_new(
    id, tenant_slug, site_id, source, host, http_port, mac, modelo, fabricante, local, updated_at
)
    SELECT id, 'default', site_id, source, host, COALESCE(http_port, 80), COALESCE(mac, ''),
           COALESCE(modelo, ''), COALESCE(fabricante, ''), COALESCE(local, ''),
           COALESCE(updated_at, datetime('now'))
    FROM recorders;

CREATE TABLE recorder_channels_new (
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
INSERT OR IGNORE INTO recorder_channels_new(
    id, tenant_slug, recorder_id, channel, title, status, local, camera_ip,
    camera_mac, camera_model, snapshot_url, imgbb_url, raw_json, updated_at
)
    SELECT rc.id, COALESCE(r.tenant_slug, 'default'), rc.recorder_id, rc.channel,
           COALESCE(rc.title, ''), COALESCE(rc.status, ''), COALESCE(rc.local, ''),
           COALESCE(rc.camera_ip, ''), COALESCE(rc.camera_mac, ''), COALESCE(rc.camera_model, ''),
           COALESCE(rc.snapshot_url, ''), COALESCE(rc.imgbb_url, ''), COALESCE(rc.raw_json, ''),
           COALESCE(rc.updated_at, datetime('now'))
    FROM recorder_channels rc
    LEFT JOIN recorders_new r ON r.id = rc.recorder_id;

DROP TABLE recorder_channels;
DROP TABLE recorders;
DROP TABLE ip_cameras;
DROP TABLE sites;

ALTER TABLE sites_new RENAME TO sites;
ALTER TABLE ip_cameras_new RENAME TO ip_cameras;
ALTER TABLE recorders_new RENAME TO recorders;
ALTER TABLE recorder_channels_new RENAME TO recorder_channels;
