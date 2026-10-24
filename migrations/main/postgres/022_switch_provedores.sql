-- Switch Provedores (menu Redes): switches da rede neutra (MikroTik CRS) onde
-- entram os links dos provedores. Lidas pela API do RouterOS, so leitura, pelo
-- IP virtual do conector. A senha fica cifrada (app.core.crypto) e e apagada
-- quando IP, porta ou conector mudam sem senha nova: a senha nunca vai para
-- outro destino sem alguem digita-la de novo.
CREATE TABLE IF NOT EXISTS provider_switches (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    nome TEXT NOT NULL,
    site TEXT NOT NULL DEFAULT '',
    ip TEXT NOT NULL,
    porta INTEGER NOT NULL DEFAULT 8728,
    connector_id TEXT NOT NULL,
    usuario TEXT NOT NULL DEFAULT '',
    senha_enc TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    ultima_leitura TEXT NOT NULL DEFAULT '',
    lido_em TEXT NOT NULL DEFAULT '',
    erro TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS provider_switches_tenant_ip_uidx ON provider_switches(tenant_slug, connector_id, ip);
CREATE INDEX IF NOT EXISTS provider_switches_tenant_idx ON provider_switches(tenant_slug, nome);
