-- Alerta Termico: pessoa detectada pelo CALOR em camera termica radiometrica.
-- termico_cameras = quais cameras do inventario o vigia le, com a regra (JSON
-- de app/services/termico_deteccao.Regra) e o horario armado ('' = 24 h).
-- termico_alertas = cada disparo; fotos e matriz em
-- data/tenants/<slug>/termico/<camera_id>/<alerta_id>/.
CREATE TABLE IF NOT EXISTS termico_cameras (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    site TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL,
    mac TEXT NOT NULL DEFAULT '',
    connector_id TEXT NOT NULL DEFAULT '',
    porta INTEGER NOT NULL DEFAULT 80,
    canal INTEGER NOT NULL DEFAULT 2,
    nome TEXT NOT NULL DEFAULT '',
    modelo TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 0,
    regra TEXT NOT NULL DEFAULT '',
    armado_de TEXT NOT NULL DEFAULT '',
    armado_ate TEXT NOT NULL DEFAULT '',
    leitura TEXT NOT NULL DEFAULT '',
    leitura_erro TEXT NOT NULL DEFAULT '',
    leitura_at TEXT NOT NULL DEFAULT '',
    fundo_c REAL,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
-- IP + conector: a mesma faixa privada se repete em usinas atras de conectores diferentes.
CREATE UNIQUE INDEX IF NOT EXISTS termico_cameras_tenant_ip_uq ON termico_cameras(tenant_slug, ip, connector_id);

CREATE TABLE IF NOT EXISTS termico_alertas (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    site TEXT NOT NULL DEFAULT '',
    camera_nome TEXT NOT NULL DEFAULT '',
    criado_at TEXT NOT NULL,
    situacao TEXT NOT NULL DEFAULT 'novo',
    temp_c REAL,
    fundo_c REAL,
    dif_c REAL,
    mancha TEXT NOT NULL DEFAULT '',
    fotos TEXT NOT NULL DEFAULT '',
    visto_por TEXT NOT NULL DEFAULT '',
    visto_at TEXT NOT NULL DEFAULT '',
    motivo_falso TEXT NOT NULL DEFAULT '',
    comentario TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS termico_alertas_tenant_criado_idx ON termico_alertas(tenant_slug, criado_at);
CREATE INDEX IF NOT EXISTS termico_alertas_tenant_situacao_idx ON termico_alertas(tenant_slug, situacao);
