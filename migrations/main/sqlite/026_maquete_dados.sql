-- Maquete 3D: dados do projeto que o cliente edita (local da obra e observacao).
ALTER TABLE maquete_projetos ADD COLUMN local TEXT NOT NULL DEFAULT '';
ALTER TABLE maquete_projetos ADD COLUMN observacao TEXT NOT NULL DEFAULT '';
