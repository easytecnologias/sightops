CREATE TABLE json_state_new (
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    k TEXT NOT NULL,
    v TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tenant_slug, k)
);

INSERT OR REPLACE INTO json_state_new(tenant_slug, k, v, updated_at)
    SELECT
        CASE
            WHEN instr(k, '__tenant__') > 0
                THEN lower(substr(k, instr(k, '__tenant__') + length('__tenant__')))
            ELSE 'default'
        END AS tenant_slug,
        CASE
            WHEN instr(k, '__tenant__') > 0
                THEN substr(k, 1, instr(k, '__tenant__') - 1)
            ELSE k
        END AS k,
        v,
        COALESCE(updated_at, datetime('now'))
    FROM json_state;

DROP TABLE json_state;
ALTER TABLE json_state_new RENAME TO json_state;
