-- Alerta: entrega do aviso aos grupos (Telegram). Linhas antigas ficam vazias
-- e nao entram no reenvio, que so olha aviso_proximo_at preenchido.
ALTER TABLE alert_incidents ADD COLUMN aviso_entregue_at TEXT NOT NULL DEFAULT '';
ALTER TABLE alert_incidents ADD COLUMN aviso_erro TEXT NOT NULL DEFAULT '';
ALTER TABLE alert_incidents ADD COLUMN aviso_tentativas INTEGER NOT NULL DEFAULT 0;
ALTER TABLE alert_incidents ADD COLUMN aviso_proximo_at TEXT NOT NULL DEFAULT '';
ALTER TABLE alert_incidents ADD COLUMN aviso_motivo TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS alert_incidents_aviso_proximo_idx ON alert_incidents(aviso_proximo_at);
