-- Historico de acoes (Configuracoes > Historico): consulta por cliente,
-- do mais novo para o mais antigo.
CREATE INDEX IF NOT EXISTS audit_log_tenant_id_idx ON audit_log(tenant_id, id);
CREATE INDEX IF NOT EXISTS audit_log_tenant_user_idx ON audit_log(tenant_id, user_id, id);
