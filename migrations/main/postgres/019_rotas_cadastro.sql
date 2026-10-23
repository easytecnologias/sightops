-- Controle de Rotas: quem paga (contratante), o contrato com quem roda
-- (operador, de 018), escolas, rotas com paradas em ordem e alunos por parada.
-- A rota cadastrada e o que o GPS confere; o aluno so conta ligado a uma parada.
-- Datas TEXT 'YYYY-MM-DD', horario TEXT 'HH:MM', preco por km TEXT decimal
-- ("4.85") para nao perder centavo em ponto flutuante.

CREATE TABLE IF NOT EXISTS rotas_contratantes (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    nome TEXT NOT NULL,
    documento TEXT NOT NULL DEFAULT '',
    contato TEXT NOT NULL DEFAULT '',
    telefone TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS rotas_contratantes_tenant_idx ON rotas_contratantes(tenant_slug, nome);

CREATE TABLE IF NOT EXISTS rotas_contratos (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    contratante_id TEXT NOT NULL,
    operador_id TEXT NOT NULL,
    numero TEXT NOT NULL DEFAULT '',
    preco_km TEXT NOT NULL DEFAULT '',
    inicio TEXT NOT NULL DEFAULT '',
    fim TEXT NOT NULL DEFAULT '',
    observacoes TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS rotas_contratos_tenant_idx ON rotas_contratos(tenant_slug, contratante_id);

CREATE TABLE IF NOT EXISTS rotas_escolas (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    nome TEXT NOT NULL,
    inep TEXT NOT NULL DEFAULT '',
    endereco TEXT NOT NULL DEFAULT '',
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS rotas_escolas_tenant_idx ON rotas_escolas(tenant_slug, nome);

CREATE TABLE IF NOT EXISTS rotas_rotas (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    contrato_id TEXT NOT NULL,
    escola_id TEXT NOT NULL DEFAULT '',
    nome TEXT NOT NULL,
    turno TEXT NOT NULL DEFAULT 'manha',
    veiculo_id TEXT NOT NULL DEFAULT '',
    motorista_id TEXT NOT NULL DEFAULT '',
    monitor_id TEXT NOT NULL DEFAULT '',
    km_previsto DOUBLE PRECISION NOT NULL DEFAULT 0,
    tolerancia_m INTEGER NOT NULL DEFAULT 300,
    observacoes TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS rotas_rotas_tenant_idx ON rotas_rotas(tenant_slug, nome);

CREATE TABLE IF NOT EXISTS rotas_paradas (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    rota_id TEXT NOT NULL,
    ordem INTEGER NOT NULL DEFAULT 0,
    nome TEXT NOT NULL,
    referencia TEXT NOT NULL DEFAULT '',
    horario TEXT NOT NULL DEFAULT '',
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS rotas_paradas_rota_idx ON rotas_paradas(tenant_slug, rota_id, ordem);

CREATE TABLE IF NOT EXISTS rotas_alunos (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    nome TEXT NOT NULL,
    matricula TEXT NOT NULL DEFAULT '',
    codigo_inep TEXT NOT NULL DEFAULT '',
    serie TEXT NOT NULL DEFAULT '',
    escola_id TEXT NOT NULL DEFAULT '',
    rota_id TEXT NOT NULL DEFAULT '',
    parada_id TEXT NOT NULL DEFAULT '',
    responsavel TEXT NOT NULL DEFAULT '',
    telefone TEXT NOT NULL DEFAULT '',
    observacoes TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS rotas_alunos_tenant_matricula_uidx
    ON rotas_alunos(tenant_slug, matricula) WHERE matricula <> '';
CREATE INDEX IF NOT EXISTS rotas_alunos_rota_idx ON rotas_alunos(tenant_slug, rota_id, parada_id);
