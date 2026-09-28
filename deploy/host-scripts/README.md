# Scripts que rodam no HOST (fora do Docker)

Estes arquivos **nao vao dentro de container**: eles configuram a rede e o disco
do proprio servidor. Ate 28/09/2026 existiam apenas em `/opt/sightops/scripts/`
e `/etc/systemd/system/` da maquina de producao, sem copia em lugar nenhum --
se o servidor se perdesse, iam junto.

Versionar aqui nao os instala. Uma copia editada neste diretorio **nao tem
efeito** ate ser levada para o caminho real e o servico recarregado.

## Onde cada coisa vai

| Arquivo | Caminho no servidor |
|---|---|
| `sightops_wireguard_sync.py` | `/opt/sightops/scripts/` |
| `sightops_ruijie_vpn_sync.py` | `/opt/sightops/scripts/` |
| `connector_iso.sh` | `/opt/sightops/scripts/` |
| `connector_routing_apply.sh` | `/opt/sightops/scripts/` |
| `connector_vnat.sh` | `/opt/sightops/scripts/` |
| `systemd/*.service`, `systemd/*.timer` | `/etc/systemd/system/` |

Depois de copiar um unit:

```bash
sudo systemctl daemon-reload
sudo systemctl restart sightops-wireguard-sync.timer
```

## O que cada um faz

**`sightops_wireguard_sync.py`** -- roda a cada minuto (timer) e sincroniza os
peers e rotas do `wg-sightops` com o cadastro de conectores.

> **Cuidado com a ordem de `CONNECTORS_JSON_CANDIDATES`.** Ele usa o PRIMEIRO
> caminho que existir. Ate 28/09/2026 o primeiro era o volume do **v2**
> (`sightops-prod-release`), que virou rede de seguranca em 18/09 -- mas o
> volume continua no disco mesmo com os containers parados. Resultado: o sync
> reconstruia peers a cada minuto a partir de um cadastro de 10 dias atras,
> recriando o peer orfao da INFORBR no `wg-sightops` e sequestrando a rota das
> cameras dela para uma interface que nao conecta. O v3 agora vem primeiro.

**`sightops_ruijie_vpn_sync.py`** -- sobe a VPN dos conectores Ruijie a partir
do cadastro.

**`connector_iso.sh` / `connector_vnat.sh` / `connector_routing_apply.sh`** --
criam a interface `wgc<N>`, a tabela de rota isolada e as regras de vnat
(NETMAP + MARK) de cada conector.

## Como conferir se o servidor esta igual ao repo

```bash
for f in sightops_wireguard_sync.py sightops_ruijie_vpn_sync.py \
         connector_iso.sh connector_routing_apply.sh connector_vnat.sh; do
  diff -q "/opt/sightops/scripts/$f" "deploy/host-scripts/$f" >/dev/null \
    && echo "OK   $f" || echo "DIFERE $f"
done
```
