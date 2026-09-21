-- Espelha migrations/auth/postgres/002_platform_admin_and_modules.sql.

ALTER TABLE users ADD COLUMN is_platform_admin INTEGER NOT NULL DEFAULT 0;

ALTER TABLE auth_tokens ADD COLUMN acting_tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL;

ALTER TABLE tenants ADD COLUMN enabled_modules TEXT DEFAULT NULL;

-- Preserva o acesso de quem ja e 'owner' hoje -- ver comentario na migration
-- espelho em migrations/auth/postgres/002_platform_admin_and_modules.sql.
UPDATE users SET is_platform_admin = 1 WHERE role = 'owner';
