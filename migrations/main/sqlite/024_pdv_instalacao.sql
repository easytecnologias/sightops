-- Instalacao do coletor PELO SightOps: o servidor entra no caixa por SSH pelo
-- IP virtual do conector da loja (nunca pelo IP publico). A senha do caixa fica
-- cifrada (app.core.crypto), so administrador mexe. ssh_hostkey guarda a chave
-- do caixa na primeira conexao: se mudar, o SightOps recusa (outro equipamento
-- no mesmo IP).
ALTER TABLE pdv_caixas ADD COLUMN pdv_host TEXT NOT NULL DEFAULT '';
ALTER TABLE pdv_caixas ADD COLUMN ssh_porta INTEGER NOT NULL DEFAULT 22;
ALTER TABLE pdv_caixas ADD COLUMN ssh_usuario TEXT NOT NULL DEFAULT '';
ALTER TABLE pdv_caixas ADD COLUMN ssh_senha_enc TEXT NOT NULL DEFAULT '';
ALTER TABLE pdv_caixas ADD COLUMN ssh_hostkey TEXT NOT NULL DEFAULT '';
ALTER TABLE pdv_caixas ADD COLUMN instalacao_estado TEXT NOT NULL DEFAULT '';
ALTER TABLE pdv_caixas ADD COLUMN instalacao_em TEXT NOT NULL DEFAULT '';
