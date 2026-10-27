-- Ponto de venda (auditoria de caixa). O coletor no caixa manda as linhas cruas
-- do Espiao e do Teclas, numeradas; o servidor interpreta (app/services/pdv_leitor.py)
-- e guarda eventos, itens e cupons. Sem IA: regra sobre os dados do proprio PDV,
-- o video do gravador e a prova.
-- Dinheiro em CENTAVOS (INTEGER): exato e igual nos dois backends.
-- Datas/horas em TEXT: dia 'YYYY-MM-DD', ts 'YYYY-MM-DD HH:MM:SS' (hora do PDV).

-- Um caixa = uma estacao do PDV (EspiaoDDMMAA.NNN, NNN = numero). O token do
-- coletor e guardado so como hash; o prefixo serve para reconhecer na tela.
CREATE TABLE IF NOT EXISTS pdv_caixas (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    nome TEXT NOT NULL,
    numero INTEGER NOT NULL DEFAULT 1,
    site TEXT NOT NULL DEFAULT '',
    connector_id TEXT NOT NULL DEFAULT '',
    gravador_host TEXT NOT NULL DEFAULT '',
    gravador_canal INTEGER NOT NULL DEFAULT 0,
    token_hash TEXT NOT NULL DEFAULT '',
    token_prefixo TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    coletor_versao TEXT NOT NULL DEFAULT '',
    ultimo_contato TEXT NOT NULL DEFAULT '',
    ultimo_evento TEXT NOT NULL DEFAULT '',
    relogio_pdv_offset_s INTEGER NOT NULL DEFAULT 0,
    relogio_dvr_offset_s INTEGER,
    relogio_dvr_medido_em TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS pdv_caixas_tenant_nome_uidx ON pdv_caixas(tenant_slug, nome);
CREATE UNIQUE INDEX IF NOT EXISTS pdv_caixas_token_uidx ON pdv_caixas(token_hash);

-- Linha crua como veio do arquivo (latin-1 ja decodificado). seq = numero da
-- linha no arquivo do dia, a partir de 1: reenvio da mesma linha nao duplica.
-- E o que permite reprocessar o dia inteiro quando a leitura melhorar.
CREATE TABLE IF NOT EXISTS pdv_linhas (
    tenant_slug TEXT NOT NULL,
    caixa_id TEXT NOT NULL,
    arquivo TEXT NOT NULL,
    dia TEXT NOT NULL,
    seq INTEGER NOT NULL,
    linha TEXT NOT NULL,
    recebido_em TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_slug, caixa_id, arquivo, dia, seq)
);

-- Evento do Espiao ja interpretado (todos os tipos, inclusive NUM/CDP).
CREATE TABLE IF NOT EXISTS pdv_eventos (
    tenant_slug TEXT NOT NULL,
    caixa_id TEXT NOT NULL,
    dia TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    tipo TEXT NOT NULL,
    cupom TEXT NOT NULL DEFAULT '',
    operador TEXT NOT NULL DEFAULT '',
    codigo TEXT NOT NULL DEFAULT '',
    descricao TEXT NOT NULL DEFAULT '',
    valor_centavos INTEGER NOT NULL DEFAULT 0,
    campos_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (tenant_slug, caixa_id, dia, seq)
);
CREATE INDEX IF NOT EXISTS pdv_eventos_tipo_idx ON pdv_eventos(tenant_slug, tipo, ts);
CREATE INDEX IF NOT EXISTS pdv_eventos_cupom_idx ON pdv_eventos(tenant_slug, caixa_id, dia, cupom);

-- Item vendido (VIT dentro de cupom) com o jeito que entrou no caixa:
-- scanner / manual / menu / outro / sem_tecla.
CREATE TABLE IF NOT EXISTS pdv_itens (
    tenant_slug TEXT NOT NULL,
    caixa_id TEXT NOT NULL,
    dia TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    cupom TEXT NOT NULL,
    operador TEXT NOT NULL DEFAULT '',
    codigo TEXT NOT NULL DEFAULT '',
    desc2 TEXT NOT NULL DEFAULT '',
    descricao TEXT NOT NULL DEFAULT '',
    quant TEXT NOT NULL DEFAULT '',
    valor_centavos INTEGER NOT NULL DEFAULT 0,
    modo TEXT NOT NULL DEFAULT 'sem_tecla',
    PRIMARY KEY (tenant_slug, caixa_id, dia, seq)
);
CREATE INDEX IF NOT EXISTS pdv_itens_cupom_idx ON pdv_itens(tenant_slug, caixa_id, dia, cupom);
CREATE INDEX IF NOT EXISTS pdv_itens_codigo_idx ON pdv_itens(tenant_slug, codigo);
CREATE INDEX IF NOT EXISTS pdv_itens_ts_idx ON pdv_itens(tenant_slug, ts);

-- Cupom: resumo para a busca. situacao = aberto / fechado / cancelado.
CREATE TABLE IF NOT EXISTS pdv_cupons (
    tenant_slug TEXT NOT NULL,
    caixa_id TEXT NOT NULL,
    dia TEXT NOT NULL,
    cupom TEXT NOT NULL,
    operador TEXT NOT NULL DEFAULT '',
    aberto_em TEXT NOT NULL DEFAULT '',
    fechado_em TEXT NOT NULL DEFAULT '',
    situacao TEXT NOT NULL DEFAULT 'aberto',
    itens INTEGER NOT NULL DEFAULT 0,
    itens_cancelados INTEGER NOT NULL DEFAULT 0,
    bipados INTEGER NOT NULL DEFAULT 0,
    digitados INTEGER NOT NULL DEFAULT 0,
    menu INTEGER NOT NULL DEFAULT 0,
    total_centavos INTEGER NOT NULL DEFAULT 0,
    pagamento TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tenant_slug, caixa_id, dia, cupom)
);
CREATE INDEX IF NOT EXISTS pdv_cupons_ts_idx ON pdv_cupons(tenant_slug, aberto_em);
CREATE INDEX IF NOT EXISTS pdv_cupons_operador_idx ON pdv_cupons(tenant_slug, operador, aberto_em);
