# Backup do SightOps v3

Ate 28/09/2026 **nao existia backup automatico**. O unico cron da maquina era de
outro projeto (parado desde 01/09) e o ultimo dump do banco era de 15/09, feito
a mao.

## Instalar

```bash
cp deploy/backup/sightops-backup.sh /home/central/scripts/
chmod 750 /home/central/scripts/sightops-backup.sh
crontab -e     # 30 3 * * * /home/central/scripts/sightops-backup.sh
```

Destino: `/mnt/dados/backups/sightops-db` -- no **segundo disco**, nao no disco
do sistema. O script aborta se `/mnt/dados` nao estiver montado; sem essa trava
ele gravaria numa pasta vazia de mesmo nome e encheria o disco da raiz em
silencio.

## Guarda tres coisas, porque nenhuma sozinha reconstroi o sistema

| O que | Quando | Tamanho |
|---|---|---|
| Banco Postgres (`sightops_prod`) | diario | ~32 MB |
| Inventario de cameras (os `.json`) | diario | ~10 MB |
| `.env.v3` + compose | diario | ~3 KB |
| Volume completo, com as fotos | domingos | ~309 MB |

**O inventario de cameras NAO esta no banco.** `cameras` e `connectors` nem sao
tabelas -- vivem em JSON no volume. Um dump do banco sozinho nao traria as
cameras de volta.

**Sem o `.env.v3` o dump e ilegivel**: a `SIGHTOPS_SECRET_KEY` decifra as senhas
de OLT. Trocar ou perder essa chave quebra tudo que esta cifrado.

## Armadilhas que ja custaram tentativa

- `tar --exclude` tem que vir ANTES dos caminhos, senao e ignorado em silencio.
- O tar do volume sai com codigo 1 porque o app reescreve `.json` durante a
  copia. Isso e normal: so o 2 e erro. Quem decide e o `gzip -t` mais o tamanho
  minimo.
- Usar imagem que JA existe no servidor (`postgres:17-alpine`): um backup nao
  pode depender de baixar imagem as 3h30 da manha.
- O script so apaga backup antigo **se o de hoje deu certo**.

## Restaurar

O inventario **nao** se restaura copiando o arquivo: o app le de um estado no
banco, e o proprio codigo garante que um inventario esvaziado de proposito nao
"ressuscite" a partir do arquivo. Tem que gravar pelo caminho oficial:

```python
from app.core.tenant_context import set_current_tenant_slug
from app.services.inventory_json import save_inventory_json
set_current_tenant_slug("default")
save_inventory_json(linhas_do_backup, mode="olt")   # ou basic / switch
```

Depois `refresh_from_inventory()` + `sync_monitoring_to_zabbix()` recriam as
entidades e os hosts.

## O que ainda falta

Os dois discos estao na **mesma maquina**. Isso protege contra erro humano e
corrupcao de banco, nao contra o servidor se perder.
