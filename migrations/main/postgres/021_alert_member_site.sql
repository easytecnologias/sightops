-- Alerta: site monitorado da pessoa (dentro do conector). Um conector pode
-- atender varios sites (condominios); so o conector nao dizia qual.
-- '' = sem site escolhido (vale o site do conector, como antes).
ALTER TABLE alert_members ADD COLUMN IF NOT EXISTS unit_site TEXT NOT NULL DEFAULT '';
