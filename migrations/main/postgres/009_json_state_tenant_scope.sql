CREATE TABLE IF NOT EXISTS json_state_new (
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    k TEXT NOT NULL,
    v TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO json_state_new(tenant_slug, k, v, updated_at)
    SELECT DISTINCT ON (tenant_slug, state_key)
        tenant_slug,
        state_key,
        v,
        updated_at
    FROM (
        SELECT
            CASE
                WHEN position('__tenant__' in k) > 0 AND split_part(k, '__tenant__', 2) <> ''
                    THEN lower(split_part(k, '__tenant__', 2))
                ELSE 'default'
            END AS tenant_slug,
            CASE
                WHEN position('__tenant__' in k) > 0
                    THEN split_part(k, '__tenant__', 1)
                ELSE k
            END AS state_key,
            v,
            COALESCE(updated_at, CURRENT_TIMESTAMP) AS updated_at
        FROM json_state
    ) src
    ORDER BY tenant_slug, state_key, updated_at DESC;

DROP TABLE json_state;
ALTER TABLE json_state_new RENAME TO json_state;

CREATE UNIQUE INDEX IF NOT EXISTS json_state_tenant_slug_k_uq
    ON json_state(tenant_slug, k);
