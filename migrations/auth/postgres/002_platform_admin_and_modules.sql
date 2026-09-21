-- Separa "admin da plataforma" (voce, dono do SaaS) de "owner de um cliente"
-- (hoje a mesma role 'owner' serve pros dois, o que deixa qualquer dono de
-- cliente enxergar a lista de todos os outros clientes). Tambem adiciona o
-- suporte pra um admin de plataforma "operar como" um cliente sem saber a
-- senha dele, e pra ligar/desligar modulos (telas) por cliente.

ALTER TABLE users ADD COLUMN is_platform_admin INTEGER NOT NULL DEFAULT 0;

ALTER TABLE auth_tokens ADD COLUMN acting_tenant_id BIGINT REFERENCES tenants(id) ON DELETE SET NULL;

-- enabled_modules: lista JSON de chaves de modulo habilitadas pro cliente.
-- NULL = todos os modulos habilitados (nao quebra clientes ja existentes).
ALTER TABLE tenants ADD COLUMN enabled_modules TEXT DEFAULT NULL;

-- Preserva o acesso de quem ja e 'owner' hoje (antes disso list_tenants/
-- create_tenant liberavam pra qualquer owner): sem isso, todo mundo que ja
-- administra o sistema perderia a visao de todos os clientes no mesmo
-- deploy que corrige o vazamento. So owners criados DEPOIS desta migration
-- (ou seja, donos de clientes novos) nascem sem is_platform_admin.
UPDATE users SET is_platform_admin = 1 WHERE role = 'owner';
