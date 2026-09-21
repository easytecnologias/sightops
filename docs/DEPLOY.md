# Deploy do SightOps v3

## O modelo de deploy (ler antes de mexer)

Producao **nao roda `git pull`**. A API e uma imagem Docker com **tag versionada**,
construida localmente; o compose aponta para a tag pelo `.env.v3`. Atualizar e:
construir a tag nova, apontar o `.env.v3` e recriar o container.

Duas consequencias praticas:

- **O uvicorn roda sem `--reload`.** Copiar arquivo para dentro do container nao
  muda o que esta no ar: o processo ja tem o codigo antigo em memoria. So o
  restart faz valer.
- **O frontend e bind-mount, nao vai na imagem.** Mudanca de tela entra copiando
  o arquivo -- mas exige subir o `?v=` no `index.html`, senao navegador e CDN
  continuam servindo o antigo. Nunca reutilize um numero de `?v=` ja usado.

## Instalacao limpa

```bash
cp .env.example .env.v3
openssl rand -hex 32          # SIGHTOPS_SECRET_KEY
openssl rand -hex 16          # SIGHTOPS_DB_PASSWORD
nano .env.v3

docker build -t sightops-api:$(date +%Y%m%d)-inicial .
# aponte CAM_SNAPSHOT_IMAGE no .env para essa tag

docker compose -f docker-compose.production.yml --env-file .env.v3 up -d
docker compose -f docker-compose.production.yml --env-file .env.v3 ps
```

Primeiro acesso: `POST /api/auth/bootstrap-admin` cria o primeiro administrador.
So funciona enquanto **nao existir nenhum usuario** -- depois disso fica travado.

## Atualizar

```bash
TAG=sightops-api:$(date +%Y%m%d)-<assunto>
docker build -t $TAG .
sed -i "s|^CAM_SNAPSHOT_IMAGE=.*|CAM_SNAPSHOT_IMAGE=$TAG|" .env.v3
docker compose -f docker-compose.production.yml --env-file .env.v3 up -d --no-deps --force-recreate cam-snapshot-api
```

Use tag com data e assunto (`20260920-hikvision`), nunca `latest`: e o que permite
voltar atras apontando o `.env.v3` para a tag anterior.

Depois de subir, confira de verdade:

```bash
docker compose -f docker-compose.production.yml --env-file .env.v3 ps
docker logs --since 5m sightops-v3-api 2>&1 | grep -iE "traceback|exception"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8087/api/system/health/live
```

## Isolamento de rede por cliente

Cada cliente entra por um tunel WireGuard proprio (`wgc<N>`), com **tabela de rota
dedicada** (`1000+N`). Isso existe porque faixas privadas se repetem entre
clientes: dois deles podem ter `192.168.10.0/24`, e sem isso um alcancaria o outro.

Os scripts vivem no **host**, em `ops/scripts/`:

| script | papel |
|---|---|
| `sightops_wireguard_sync.py` | mantem os peers em dia com o cadastro |
| `connector_routing_apply.sh` | cria interfaces, rotas e regras por cliente |
| `connector_vnat.sh` | NAT 1:1 (IP virtual -> IP real) + marca o pacote para a tabela do cliente |
| `connector_iso.sh` | provisiona um cliente isolado novo |

Dois pontos que ja custaram caro:

**`rp_filter` precisa ser `2` (loose).** No modo estrito o kernel valida o caminho
de volta pela tabela principal e descarta a resposta: o tunel fecha handshake e
nenhum dado volta.

**O IP do proprio roteador tambem precisa de rota exclusiva.** Ter tabela por
cliente nao basta -- o trafego so entra nela se o destino for exclusivo daquele
cliente (faixa `10.201.0.0/24`, um `/31` por tunel) ou passar pelo NAT virtual.
Um IP da faixa compartilhada antiga sai pela tabela padrao e chega no roteador de
**outro cliente**.

## Backup

Tres coisas, e as tres juntas -- cada uma sozinha nao restaura nada:

1. **Banco** (`docker compose exec postgres pg_dump ...`)
2. **Volume `data/`** -- inventario, fotos e `connectors.json` (token e chave
   privada de WireGuard de cada cliente)
3. **`.env.v3`** -- sem a `SIGHTOPS_SECRET_KEY` as senhas do banco ficam ilegiveis

## Verificacao de seguranca

```bash
python scripts/audita_autorizacao.py --teto 0
```

Lista rota de escrita sem papel declarado e falha se houver. Desde 20/09/2026 o
padrao e negar, entao o esperado e zero.
