-- Cadastro de OLT (Postgres).
--
-- Ate aqui nao existia registro de OLT em lugar nenhum: as 8 operacoes de OLT
-- recebiam olt_ip/usuario/senha no corpo de cada requisicao, e a lista de OLTs
-- da tela de ONU era derivada das ONUs ja coletadas -- ou seja, uma OLT nova
-- nao aparecia ate alguem coletar dela.
--
-- vendor e model sao colunas separadas de proposito. Hoje so ha Fiberhome
-- (8820i e 4840e), mas o roteamento por modelo ja existe no olt_service; com
-- fabricante explicito, entrar Huawei/ZTE depois nao exige remodelar a tabela.
--
-- password_enc guarda o texto cifrado por app/core/crypto.py, nunca a senha
-- crua. O nome da coluna diz isso pra ninguem gravar direto por engano.

CREATE TABLE IF NOT EXISTS olts (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    site_id BIGINT REFERENCES sites(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    vendor TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    password_enc TEXT NOT NULL DEFAULT '',
    connector_id TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indice unico criado com nome explicito, nao UNIQUE(...) inline: e a licao da
-- 001: UNIQUE inline gera nome automatico (_key), e uma migration futura que
-- procure o indice pelo nome _uq nao o encontraria, criando um duplicado e
-- fazendo instalacao nova divergir de banco existente.
CREATE UNIQUE INDEX IF NOT EXISTS olts_tenant_slug_host_uq
    ON olts(tenant_slug, host);

-- Busca da tela e sempre dentro do tenant.
CREATE INDEX IF NOT EXISTS olts_tenant_slug_idx
    ON olts(tenant_slug);
