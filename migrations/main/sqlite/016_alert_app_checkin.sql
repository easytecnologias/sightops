-- Prontidao do app do Alerta: o que o aparelho informa quando abre o app.
-- gps_permission: granted | denied | prompt | '' (o app nao soube dizer).
ALTER TABLE alert_app_sessions ADD COLUMN gps_permission TEXT NOT NULL DEFAULT '';
ALTER TABLE alert_app_sessions ADD COLUMN battery INTEGER;
ALTER TABLE alert_app_sessions ADD COLUMN app_version TEXT NOT NULL DEFAULT '';
ALTER TABLE alert_app_sessions ADD COLUMN checkin_at TEXT NOT NULL DEFAULT '';
