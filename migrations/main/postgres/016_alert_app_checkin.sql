-- Prontidao do app do Alerta: o que o aparelho informa quando abre o app.
-- gps_permission: granted | denied | prompt | '' (o app nao soube dizer).
-- A central usa isso para achar celular que nao vai mandar localizacao
-- ANTES de alguem precisar apertar o botao.
ALTER TABLE alert_app_sessions ADD COLUMN IF NOT EXISTS gps_permission TEXT NOT NULL DEFAULT '';
ALTER TABLE alert_app_sessions ADD COLUMN IF NOT EXISTS battery INTEGER;
ALTER TABLE alert_app_sessions ADD COLUMN IF NOT EXISTS app_version TEXT NOT NULL DEFAULT '';
ALTER TABLE alert_app_sessions ADD COLUMN IF NOT EXISTS checkin_at TEXT NOT NULL DEFAULT '';
