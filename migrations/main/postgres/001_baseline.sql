-- Baseline do banco principal (Postgres).
-- Descreve o schema correto e completo. Banco pre-existente adota esta versao
-- sem executar (ver app/core/migrations.py) e e levado ate aqui pela 002.
--
-- As chaves unicas por tenant sao criadas como CREATE UNIQUE INDEX no fim do
-- arquivo, com os MESMOS nomes que a 002 usa -- nao como UNIQUE(...) inline.
--
-- Isso importa: UNIQUE inline faz o Postgres gerar uma constraint com nome
-- automatico (sites_tenant_slug_name_key), que nao casa com o
-- `CREATE UNIQUE INDEX IF NOT EXISTS sites_tenant_slug_name_uq` da 002. O
-- IF NOT EXISTS entao nao encontra nada, cria um segundo indice identico, e a
-- instalacao nova termina com indice duplicado enquanto o banco adotado tem so
-- um -- exatamente a divergencia entre os dois caminhos que este runner existe
-- pra impedir. Medido num Postgres 16 real antes da correcao.
--
-- recorder_channels e a excecao proposital: la o UNIQUE inline gera
-- recorder_channels_recorder_id_channel_key, que e o nome que o banco de
-- producao ja tem, e a 002 nao mexe nessa tabela. Inline ali converge.

CREATE TABLE IF NOT EXISTS sites (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings_kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS json_state (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ip_cameras (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    site_id BIGINT REFERENCES sites(id) ON DELETE SET NULL,
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recorders (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    site_id BIGINT REFERENCES sites(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    host TEXT NOT NULL,
    http_port INTEGER NOT NULL DEFAULT 80,
    mac TEXT DEFAULT '',
    modelo TEXT DEFAULT '',
    fabricante TEXT DEFAULT '',
    local TEXT DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recorder_channels (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    recorder_id BIGINT NOT NULL REFERENCES recorders(id) ON DELETE CASCADE,
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(recorder_id, channel)
);

-- Chaves unicas por tenant. Nomes identicos aos da 002 de proposito (ver
-- cabecalho): assim a 002 encontra os indices via IF NOT EXISTS e vira no-op
-- num banco novo, em vez de criar um segundo indice.
CREATE UNIQUE INDEX IF NOT EXISTS sites_tenant_slug_name_uq
    ON sites(tenant_slug, name);
CREATE UNIQUE INDEX IF NOT EXISTS ip_cameras_tenant_slug_ip_uq
    ON ip_cameras(tenant_slug, ip);
CREATE UNIQUE INDEX IF NOT EXISTS recorders_tenant_slug_source_host_port_uq
    ON recorders(tenant_slug, source, host, http_port);
