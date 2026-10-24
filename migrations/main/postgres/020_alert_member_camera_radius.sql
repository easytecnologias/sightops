-- Alerta: raio (metros) das cameras "no local do alerta", definido por pessoa.
-- 0 = padrao do sistema (NEARBY_RADIUS_M, 20 m).
ALTER TABLE alert_members ADD COLUMN IF NOT EXISTS camera_radius_m INTEGER NOT NULL DEFAULT 0;
