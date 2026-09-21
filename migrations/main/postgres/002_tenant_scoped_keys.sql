-- Leva um banco pre-existente ate a forma da baseline 001.
--
-- Num banco criado pela 001 esta migration e inteiramente no-op (tudo aqui e
-- condicional). Num banco antigo ela adiciona tenant_slug, cria as chaves
-- unicas por tenant e -- o ponto principal -- remove as UNIQUE do schema
-- original, que sobreviviam ao CREATE TABLE IF NOT EXISTS e impediam dois
-- clientes de terem o mesmo IP, o mesmo nome de site ou o mesmo gravador.
--
-- Nao usar '%' neste arquivo: o driver interpreta como placeholder de parametro.

ALTER TABLE sites             ADD COLUMN IF NOT EXISTS tenant_slug TEXT NOT NULL DEFAULT 'default';
ALTER TABLE ip_cameras        ADD COLUMN IF NOT EXISTS tenant_slug TEXT NOT NULL DEFAULT 'default';
ALTER TABLE recorders         ADD COLUMN IF NOT EXISTS tenant_slug TEXT NOT NULL DEFAULT 'default';
ALTER TABLE recorder_channels ADD COLUMN IF NOT EXISTS tenant_slug TEXT NOT NULL DEFAULT 'default';

CREATE UNIQUE INDEX IF NOT EXISTS sites_tenant_slug_name_uq
    ON sites(tenant_slug, name);
CREATE UNIQUE INDEX IF NOT EXISTS ip_cameras_tenant_slug_ip_uq
    ON ip_cameras(tenant_slug, ip);
CREATE UNIQUE INDEX IF NOT EXISTS recorders_tenant_slug_source_host_port_uq
    ON recorders(tenant_slug, source, host, http_port);

-- Dropa toda UNIQUE que nao inclui tenant_slug nas tres tabelas escopadas.
-- Feito por descoberta no catalogo em vez de por nome fixo porque o nome
-- gerado pelo Postgres depende de como a tabela foi criada.
--
-- recorder_channels fica de fora de proposito: UNIQUE(recorder_id, channel) ja
-- e por tenant via FK pra recorders, e dropar liberaria canal duplicado.
DO $do$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT con.conrelid::regclass::text AS tbl, con.conname AS name
        FROM pg_constraint con
        JOIN pg_class cls ON cls.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
        WHERE con.contype = 'u'
          AND nsp.nspname NOT IN ('pg_catalog', 'information_schema')
          AND cls.relname IN ('sites', 'ip_cameras', 'recorders')
          AND NOT EXISTS (
              SELECT 1
              FROM unnest(con.conkey) AS k
              JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k
              WHERE att.attname = 'tenant_slug'
          )
    LOOP
        EXECUTE 'ALTER TABLE ' || r.tbl || ' DROP CONSTRAINT ' || quote_ident(r.name);
    END LOOP;
END
$do$;
