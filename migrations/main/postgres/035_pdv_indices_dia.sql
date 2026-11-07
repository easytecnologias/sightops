-- PDV: indices por dia. As telas (Visao geral, Momentos, Lojas, Rankings) filtram
-- por cliente + dia (+ tipo/caixa); sem indice com `dia`, o banco usava
-- (tenant_slug, tipo, ts) e varria o historico inteiro do cliente a cada consulta
-- (Momentos chegou a 100 s em 07/11/2026, com 1,6 mi de eventos).
-- Em producao foram criados antes com CREATE INDEX CONCURRENTLY: aqui e no-op.
CREATE INDEX IF NOT EXISTS pdv_eventos_dia_tipo_idx ON pdv_eventos(tenant_slug, dia, tipo, caixa_id);
CREATE INDEX IF NOT EXISTS pdv_itens_dia_idx ON pdv_itens(tenant_slug, dia, caixa_id);
