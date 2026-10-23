-- Controle de Rotas (transporte escolar / PNATE): quem roda (operador: frota
-- propria da prefeitura ou empresa contratada), os veiculos e os motoristas.
-- Datas de validade sao TEXT 'YYYY-MM-DD' (vazio = nao informado), iguais nos
-- dois backends; a situacao (ok / vence / vencido) e calculada no Python.

CREATE TABLE IF NOT EXISTS rotas_operadores (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    nome TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'empresa',
    documento TEXT NOT NULL DEFAULT '',
    contato TEXT NOT NULL DEFAULT '',
    telefone TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS rotas_operadores_tenant_idx ON rotas_operadores(tenant_slug, nome);

CREATE TABLE IF NOT EXISTS rotas_veiculos (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    operador_id TEXT NOT NULL DEFAULT '',
    placa TEXT NOT NULL,
    modelo TEXT NOT NULL DEFAULT '',
    tipo TEXT NOT NULL DEFAULT 'onibus',
    lugares INTEGER NOT NULL DEFAULT 0,
    ano INTEGER NOT NULL DEFAULT 0,
    vistoria_validade TEXT NOT NULL DEFAULT '',
    autorizacao_numero TEXT NOT NULL DEFAULT '',
    autorizacao_validade TEXT NOT NULL DEFAULT '',
    seguro_validade TEXT NOT NULL DEFAULT '',
    observacoes TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS rotas_veiculos_tenant_placa_uidx ON rotas_veiculos(tenant_slug, placa);
CREATE INDEX IF NOT EXISTS rotas_veiculos_operador_idx ON rotas_veiculos(tenant_slug, operador_id);

CREATE TABLE IF NOT EXISTS rotas_motoristas (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    operador_id TEXT NOT NULL DEFAULT '',
    nome TEXT NOT NULL,
    funcao TEXT NOT NULL DEFAULT 'motorista',
    cpf TEXT NOT NULL DEFAULT '',
    telefone TEXT NOT NULL DEFAULT '',
    cnh_numero TEXT NOT NULL DEFAULT '',
    cnh_categoria TEXT NOT NULL DEFAULT '',
    cnh_validade TEXT NOT NULL DEFAULT '',
    curso_validade TEXT NOT NULL DEFAULT '',
    antecedentes_data TEXT NOT NULL DEFAULT '',
    observacoes TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS rotas_motoristas_tenant_cpf_uidx
    ON rotas_motoristas(tenant_slug, cpf) WHERE cpf <> '';
CREATE INDEX IF NOT EXISTS rotas_motoristas_operador_idx ON rotas_motoristas(tenant_slug, operador_id);
