-- Rotas de cabo do projeto planejado (SQLite).
--
-- Ate aqui a metragem de fibra e de UTP saia da linha reta entre dois
-- equipamentos (+ margem) ou de um numero digitado a mao. A rota guarda o
-- caminho de verdade, ponto a ponto, normalmente de poste em poste.
--
-- kind: fiber_main (OLT/DIO -> emenda/CTO), fiber_drop (CTO -> caixa),
-- utp (caixa/switch -> camera).
-- path_json: lista de pontos {"lat": .., "lon": .., "device_id": ..}; quando
-- o ponto e um equipamento do projeto (poste, CTO...), device_id faz a rota
-- acompanhar o equipamento se ele for movido.
-- length_m: metragem do tracado na ultima gravacao (o servidor recalcula).

CREATE TABLE IF NOT EXISTS planning_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_slug TEXT NOT NULL,
    route_key TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    from_device_id INTEGER,
    to_device_id INTEGER,
    path_json TEXT NOT NULL DEFAULT '[]',
    length_m REAL NOT NULL DEFAULT 0,
    cable_model TEXT NOT NULL DEFAULT '',
    fiber_count INTEGER NOT NULL DEFAULT 0,
    slack_m REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(project_id) REFERENCES planning_projects(id) ON DELETE CASCADE,
    FOREIGN KEY(from_device_id) REFERENCES planning_devices(id) ON DELETE SET NULL,
    FOREIGN KEY(to_device_id) REFERENCES planning_devices(id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS planning_routes_tenant_key_uq
    ON planning_routes(tenant_slug, route_key);
CREATE INDEX IF NOT EXISTS planning_routes_project_idx
    ON planning_routes(tenant_slug, project_id, kind);
