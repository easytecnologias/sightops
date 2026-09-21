-- O mesmo IP privado pode existir em sites/conectores diferentes do tenant.
DROP INDEX IF EXISTS olts_tenant_slug_host_uq;

CREATE UNIQUE INDEX IF NOT EXISTS olts_tenant_connector_site_host_uq
    ON olts(tenant_slug, connector_id, COALESCE(site_id, 0), host);
