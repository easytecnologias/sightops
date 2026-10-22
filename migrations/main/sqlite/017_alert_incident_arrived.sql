-- Alerta: etapa "equipe chegou ao local" (o status continua 'dispatched').
ALTER TABLE alert_incidents ADD COLUMN arrived_at TEXT NOT NULL DEFAULT '';
ALTER TABLE alert_incidents ADD COLUMN arrived_by TEXT NOT NULL DEFAULT '';
