-- Automacoes: "quando a camera termica detectar, faca isso" (speed vai ao
-- preset, saida de alarme liga refletor/sirene). modo='simular' so registra o
-- que faria; 'valer' aciona o equipamento do cliente.
-- automacao_execucoes = historico de cada acao, com o resultado.
CREATE TABLE IF NOT EXISTS automacoes (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    nome TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    modo TEXT NOT NULL DEFAULT 'simular',
    origem_camera_id TEXT NOT NULL DEFAULT '',
    intervalo_s INTEGER NOT NULL DEFAULT 120,
    acoes TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS automacoes_tenant_idx ON automacoes(tenant_slug, ativo);

CREATE TABLE IF NOT EXISTS automacao_execucoes (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    automacao_id TEXT NOT NULL,
    alerta_id TEXT NOT NULL DEFAULT '',
    modo TEXT NOT NULL DEFAULT 'simular',
    acao TEXT NOT NULL DEFAULT '',
    ok INTEGER NOT NULL DEFAULT 0,
    resposta TEXT NOT NULL DEFAULT '',
    criado_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS automacao_execucoes_tenant_idx ON automacao_execucoes(tenant_slug, automacao_id, criado_at);
