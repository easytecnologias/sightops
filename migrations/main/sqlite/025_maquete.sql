-- Maquete 3D: o cliente envia a planta (PDF do CAD), o SightOps le as paredes
-- e monta a maquete; nela o cliente posiciona cameras, eletrocalha, caixas e
-- rack. `leitura` = o que saiu do PDF (paredes por pavimento, JSON); `layout` =
-- o que o cliente montou por cima (JSON). Arquivos (PDF e texturas do piso) em
-- data/tenants/<slug>/maquete/<id>/.
CREATE TABLE IF NOT EXISTS maquete_projetos (
    id TEXT PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    nome TEXT NOT NULL DEFAULT '',
    arquivo TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'processando',
    erro TEXT NOT NULL DEFAULT '',
    leitura TEXT NOT NULL DEFAULT '',
    layout TEXT NOT NULL DEFAULT '',
    criado_por TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS maquete_projetos_tenant_idx ON maquete_projetos(tenant_slug, updated_at);
