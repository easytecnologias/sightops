-- Alerta: etapa "equipe chegou ao local", entre "equipe enviada" e
-- "encerrado". Mede o tempo ate a ajuda chegar de fato. O status nao muda
-- (continua 'dispatched'): app, escalonamento e filtros seguem iguais.
ALTER TABLE alert_incidents ADD COLUMN IF NOT EXISTS arrived_at TEXT NOT NULL DEFAULT '';
ALTER TABLE alert_incidents ADD COLUMN IF NOT EXISTS arrived_by TEXT NOT NULL DEFAULT '';
