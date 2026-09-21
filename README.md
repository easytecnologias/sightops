# SightOps v3

Gestao de CFTV: inventario de cameras, gravadores (DVR/NVR) e OLTs, monitoramento,
controle de acesso e alerta de panico -- multi-cliente, com isolamento de rede por
cliente via WireGuard.

Este repositorio e a **fonte da verdade do v3**, extraido do que roda em producao
em 20/09/2026. Ate entao o codigo vivia so no servidor, com patches aplicados a
mao no container -- por isso um repositorio novo, e nao um branch do anterior.

## Como isto se organiza

| pasta | o que e |
|---|---|
| `app/` | API FastAPI: rotas em `app/api/endpoints/`, regras em `app/services/` |
| `frontend/` | SPA servida pelo nginx (HTML/CSS/JS puro, sem build) |
| `ops/scripts/` | scripts que rodam no **host**, nao no container: WireGuard, rotas e NAT do isolamento por cliente |
| `deploy/` | nginx, Grafana e afins |
| `migrations/` | migracoes de banco (PostgreSQL e SQLite) |
| `docker-compose.production.yml` | a stack inteira |

Uma distincao que economiza tempo: **o frontend nao esta dentro da imagem**. Ele e
servido por bind-mount, entao atualizar tela nao exige rebuild -- mas exige subir o
`?v=` do arquivo no `index.html`, senao o navegador (e a CDN) continua servindo o
antigo.

## Subir em um servidor novo

Requisitos: Docker com Compose v2, e portas livres conforme o `.env`.

```bash
git clone <este-repositorio> sightops-v3 && cd sightops-v3
cp .env.example .env
openssl rand -hex 32   # gere um valor para SIGHTOPS_SECRET_KEY
nano .env              # preencha os campos obrigatorios
docker compose -f docker-compose.production.yml --env-file .env up -d
```

Detalhes de producao -- build da imagem, atualizacao sem downtime, isolamento de
rede por cliente e backup -- estao em [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Duas coisas que nao podem ser perdidas

**`SIGHTOPS_SECRET_KEY`** cifra as senhas de OLT e equipamentos guardadas no banco.
Trocar ou perder essa chave torna ilegivel tudo que ja foi cifrado. Ela pertence ao
backup junto do banco: um nao serve sem o outro.

**`data/`** guarda `connectors.json`, com o token e a **chave privada de WireGuard de
cada cliente**. Esta no `.gitignore` e deve continuar fora de qualquer repositorio.

## Seguranca da API

Autorizacao por papel (`viewer` < `operator` < `admin` < `owner`) declarada em
`app/core/security.py`. Desde 20/09/2026 o padrao para rota de **escrita** e
**negar**: rota sem papel declarado responde 403 em vez de liberar.

Para conferir que continua assim -- e util em CI:

```bash
python scripts/audita_autorizacao.py --teto 0
```

Ele lista toda rota de escrita sem papel declarado e falha acima do teto.
