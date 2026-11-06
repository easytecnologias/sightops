-- Escalonamento: alarme sem resposta avisa de novo (por cliente).
CREATE TABLE IF NOT EXISTS termico_config (
    tenant_slug TEXT PRIMARY KEY,
    escalar_min INTEGER NOT NULL DEFAULT 10,
    escalar_vezes INTEGER NOT NULL DEFAULT 2,
    updated_at TEXT NOT NULL DEFAULT ''
);
ALTER TABLE termico_alertas ADD COLUMN escalado_n INTEGER NOT NULL DEFAULT 0;
ALTER TABLE termico_alertas ADD COLUMN escalado_at TEXT NOT NULL DEFAULT '';
