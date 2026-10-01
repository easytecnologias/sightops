-- Credencial de acesso a gravador DVR/NVR (SQLite).
--
-- O inventario de gravador nunca guardou senha (ver `editable_fields` em
-- app/api/endpoints/nvr.py), entao entrar num gravador ja cadastrado pedia
-- tudo de novo. Aqui a senha e digitada uma vez e o servidor a resolve dali
-- pra frente -- mesmo desenho de camera_credentials (migration 010).
--
-- A chave e (host, port): o mesmo IP em porta diferente e outro equipamento.
-- password_enc guarda o texto cifrado por app/core/crypto.py, nunca a senha
-- crua; o nome da coluna diz isso pra ninguem gravar direto por engano.

CREATE TABLE IF NOT EXISTS recorder_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL DEFAULT 'default',
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 0,
    username TEXT NOT NULL DEFAULT '',
    password_enc TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS recorder_credentials_tenant_host_port_uq
    ON recorder_credentials(tenant_slug, host, port);
