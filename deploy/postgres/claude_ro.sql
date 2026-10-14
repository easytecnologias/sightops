-- Usuario de consulta para o Claude: so SELECT, sessao somente leitura.
-- Sem senha: so entra por conexao local dentro do container (pg_hba "local trust");
-- pela rede (scram) nao autentica.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claude_ro') THEN
    CREATE ROLE claude_ro LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END $$;
ALTER ROLE claude_ro SET default_transaction_read_only = on;
ALTER ROLE claude_ro SET statement_timeout = '15s';
ALTER ROLE claude_ro CONNECTION LIMIT 3;
GRANT CONNECT ON DATABASE sightops_prod TO claude_ro;
GRANT USAGE ON SCHEMA public TO claude_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO claude_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE sightops_prod IN SCHEMA public GRANT SELECT ON TABLES TO claude_ro;
