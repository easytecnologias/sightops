CREATE TABLE IF NOT EXISTS planning_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL,
    project_key TEXT NOT NULL,
    name TEXT NOT NULL,
    client_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    kmz_layer_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS planning_projects_tenant_key_uq
    ON planning_projects(tenant_slug, project_key);

CREATE TABLE IF NOT EXISTS planning_project_sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(project_id) REFERENCES planning_projects(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS planning_sites_project_name_uq
    ON planning_project_sites(tenant_slug, project_id, name);

CREATE TABLE IF NOT EXISTS planning_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL,
    device_key TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    site_id INTEGER,
    parent_id INTEGER,
    device_type TEXT NOT NULL,
    name TEXT NOT NULL,
    ip TEXT NOT NULL DEFAULT '',
    manufacturer TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    pon TEXT NOT NULL DEFAULT '',
    onu_position TEXT NOT NULL DEFAULT '',
    latitude REAL,
    longitude REAL,
    reference_image_url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(project_id) REFERENCES planning_projects(id) ON DELETE CASCADE,
    FOREIGN KEY(site_id) REFERENCES planning_project_sites(id) ON DELETE SET NULL,
    FOREIGN KEY(parent_id) REFERENCES planning_devices(id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS planning_devices_tenant_key_uq
    ON planning_devices(tenant_slug, device_key);
CREATE INDEX IF NOT EXISTS planning_devices_project_idx
    ON planning_devices(tenant_slug, project_id, device_type);
