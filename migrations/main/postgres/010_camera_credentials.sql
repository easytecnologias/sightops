-- Credencial de acesso a camera (Postgres).
--
-- Duas tabelas, nao uma com coluna opcional: mais simples de indexar e de ler
-- do que uma unica tabela com linhas de dois formatos (senha do site vs.
-- senha de uma camera especifica).
--
-- camera_site_credentials: senha padrao de um site (a maioria dos clientes
-- usa a mesma senha em todo o parque de cameras de um site).
-- camera_mac_credentials: senha de UMA camera especifica (por MAC, que nao
-- muda quando a camera troca de IP) -- sobrepoe a do site quando existe.
--
-- password_enc guarda o texto cifrado por app/core/crypto.py, nunca a senha
-- crua. O nome da coluna diz isso pra ninguem gravar direto por engano.

CREATE TABLE IF NOT EXISTS camera_site_credentials (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    site TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    password_enc TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS camera_site_credentials_tenant_site_uq
    ON camera_site_credentials(tenant_slug, site);

CREATE TABLE IF NOT EXISTS camera_mac_credentials (
    id BIGSERIAL PRIMARY KEY,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    mac TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    password_enc TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS camera_mac_credentials_tenant_mac_uq
    ON camera_mac_credentials(tenant_slug, mac);
