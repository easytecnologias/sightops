CREATE TABLE IF NOT EXISTS monitoring_profiles (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    profile_key TEXT NOT NULL,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    vendor TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    interval_seconds INTEGER NOT NULL DEFAULT 120,
    failure_threshold INTEGER NOT NULL DEFAULT 2,
    config_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS monitoring_profiles_tenant_key_uq ON monitoring_profiles(tenant_slug, profile_key);

CREATE TABLE IF NOT EXISTS monitoring_entities (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL DEFAULT '',
    parent_key TEXT NOT NULL DEFAULT '',
    site TEXT NOT NULL DEFAULT '',
    connector_id TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL,
    profile_key TEXT NOT NULL DEFAULT '',
    monitoring_enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'unknown',
    previous_status TEXT NOT NULL DEFAULT 'unknown',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_checked_at TIMESTAMPTZ,
    last_changed_at TIMESTAMPTZ,
    zabbix_hostid TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS monitoring_entities_tenant_key_uq ON monitoring_entities(tenant_slug, entity_key);
CREATE INDEX IF NOT EXISTS monitoring_entities_tenant_status_idx ON monitoring_entities(tenant_slug, status, entity_type);

CREATE TABLE IF NOT EXISTS monitoring_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS monitoring_events_tenant_created_idx ON monitoring_events(tenant_slug, created_at DESC);
