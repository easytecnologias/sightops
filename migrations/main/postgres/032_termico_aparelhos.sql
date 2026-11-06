-- Celulares que recebem o Alerta Termico por notificacao (Firebase).
-- Quem recebe e decidido na hora do envio pelo cadastro atual do usuario
-- (ativo, modulo, sites): aqui fica so de quem e o aparelho.
-- O token do Firebase identifica o aparelho e muda de tempos em tempos.
CREATE TABLE IF NOT EXISTS termico_aparelhos (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    usuario_id INTEGER NOT NULL DEFAULT 0,
    usuario TEXT NOT NULL DEFAULT '',
    token TEXT NOT NULL,
    plataforma TEXT NOT NULL DEFAULT '',
    criado_at TEXT NOT NULL DEFAULT '',
    visto_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS termico_aparelhos_token_uq ON termico_aparelhos(token);
CREATE INDEX IF NOT EXISTS termico_aparelhos_tenant_idx ON termico_aparelhos(tenant_slug);
