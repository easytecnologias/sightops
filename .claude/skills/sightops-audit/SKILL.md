---
name: sightops-audit
description: Analisa o sistema SightOps (cam-snapshot-web-v2) inteiro — backend FastAPI, frontend, Docker/stack de produção, conectores (OLT, RouterOS/WireGuard, câmeras) — e revisa as mudanças recentes (diff não commitado + últimos commits) para achar bugs, riscos de arquitetura, segurança, performance e regressões introduzidas pelas mudanças. Cobre também prontidão para SaaS multi-cliente: isolamento entre tenants, filas/jobs, HTTPS, concorrência, rate limit por cliente. Use quando o usuário pedir para auditar, revisar mudanças, ou avaliar se o sistema está pronto pra vender/escalar pra vários clientes.
---


> **Nao e esta skill se o usuario relatou UM sintoma concreto que ele esta vendo agora**
> ("apaguei e voltou", "o filtro nao funciona", "ta lento"). Nesse caso use
> `sightops-bug-producao`, que vai do sintoma ate a correcao publicada em producao.
> Esta skill aqui e para varredura ampla: achar o que ainda ninguem reclamou.

# SightOps Audit Skill

Use esta skill quando o usuário pedir para auditar o SightOps, revisar o projeto inteiro, revisar as mudanças/diff atuais, investigar uma regressão recente, ou pedir um "raio-x" do sistema antes de fazer deploy/push.

Repositório: `C:\PROJETOS\cam-snapshot-web-v2`. É o mesmo sistema também referido como `cam-snapshot-web` / SightOps nas conversas com o usuário.

## Objetivo

Duas coisas em conjunto, não uma OU outra:

1. **Sistema inteiro**: mapear arquitetura, achar bugs reais, falhas de segurança, inconsistências entre backend/frontend/banco/Docker/conectores.
2. **Mudanças**: entender o que mudou recentemente (working tree sujo + últimos commits ainda não enviados ao `origin`) e avaliar se essas mudanças quebram algo, introduzem regressão, ou ficaram incompletas.

Não altere código na primeira passada, a menos que o usuário peça explicitamente. Primeiro entenda, mapeie e gere relatório.

## Stack conhecida (referência — confirme lendo os arquivos, pode ter mudado)

- **Backend**: FastAPI em `app/` (`app/api/endpoints/`, `app/services/`, `app/core/`, `app/models/`, `app/cli/tools/`). Entrypoint `api.py` / `app/main.py`.
- **Frontend**: Vue 3 + Vite + Tailwind em `frontend/`. Há também um `web/` legado — verificar se ainda está em uso ou é resíduo.
- **Auth**: JWT em `app/core/security.py`.
- **Banco**: PostgreSQL (`sightops-postgres` no compose de produção); há também `data/sightops.db` (SQLite) — confirmar qual é o ativo em cada ambiente.
- **Streaming**: go2rtc + ffmpeg para transcoding H265→H264, WebRTC/MJPEG para live view (ver `README_ws_test_plugavel.md`, endpoints `live.py`/`ws.py`).
- **Conectores externos**: RouterOS/WireGuard (VPN entre sites), OLTs Fiberhome/Huawei (`olt_4840e_*`, `olt_8820i_*`), scan/discovery de câmeras Intelbras.
- **Multi-tenant**: há scripts de migração de tenant (`migrate_incoforte_tenant.py`) — sistema parece estar migrando para SaaS multi-cliente.
- **Deploy**: Docker Compose (`docker-compose.platform.yml`) sobe API + nginx + Postgres + Zabbix + Grafana. Publicação de imagem via GHCR (`.github/workflows/docker-image.yml`). Ver `docs/PLATFORM_STACK.md`.
- **Produção**: servidor 10.10.12.7 (ver memória do projeto).

Trate esta seção como ponto de partida, não como verdade absoluta — o repositório tem muitos scripts soltos na raiz (`deploy-*.sh`, `fix-*.sh`, `check-*.sh`, `_tmp_*`) que indicam iteração rápida em produção; confirme o que está realmente em uso antes de reportar como bug.

## Processo obrigatório

### 1. Mudanças primeiro (o que é novo)

```bash
git -C "C:\PROJETOS\cam-snapshot-web-v2" status
git -C "C:\PROJETOS\cam-snapshot-web-v2" diff
git -C "C:\PROJETOS\cam-snapshot-web-v2" log --oneline -30
git -C "C:\PROJETOS\cam-snapshot-web-v2" diff origin/main...HEAD --stat
```

- Liste o que está modificado e não commitado (working tree) separado do que já foi commitado mas não enviado (`ahead of origin`).
- Para cada arquivo alterado, entenda a intenção da mudança (leia a função/rota inteira, não só o diff) e verifique se ela é consistente com o resto do sistema que a chama/consome.
- Preste atenção especial em: rotas de API alteradas sem atualizar o frontend correspondente; mudanças em `security.py`/auth sem revisão de todos os endpoints; alterações em serviços de scan/ping que rodam em background/thread; mudanças de schema sem migration.

### 2. Sistema inteiro (mapa)

1. Mapear estrutura do projeto (`app/`, `frontend/`, `deploy/`, `docs/`, `scripts/`).
2. Identificar stack, serviços, banco, filas, integrações, Docker (releia a seção acima e confirme contra o código atual).
3. Ler arquivos de entrada: `README.md`, `CLAUDE.md` (se existir), `docs/*.md`, `requirements.txt`, `frontend/package.json`, `docker-compose*.yml`, `Dockerfile`, `.env.example`.
4. Montar grafo mental do sistema: frontend ↔ API ↔ banco, jobs/workers de scan, WebSocket/live streaming, conectores externos (OLT/RouterOS/câmeras), autenticação/permissões, deploy.
5. Rodar verificações seguras, se existirem: lint/typecheck do frontend, testes Python, `python -m compileall .`, busca por segredos.
6. Procurar bugs por categoria (ver abaixo).

## Categorias de bug

### Críticos
- perda de dados, vazamento de senha/token/chave (atenção: há `.env`, chaves SSH `_tmp_sightops_deploy_ed25519` e zips com "saas-keys" soltos na raiz do repo — verificar se estão no `.gitignore`)
- autenticação quebrada, bypass de autorização, SQL injection, execução remota
- problema que impede build/start da API ou do compose de produção

### Altos
- inconsistência de schema/banco (Postgres vs SQLite `data/sightops.db`)
- endpoint sem validação, falta de tratamento de erro em fluxo principal (scan de câmeras, streaming)
- race condition em jobs de scan/ping em background
- CORS permissivo em produção, Docker/deploy quebrado
- regressão introduzida por uma mudança recente (ver seção "Mudanças")

### Médios
- performance ruim (scans síncronos bloqueantes, queries N+1)
- estado inconsistente no frontend após mudança de API
- duplicação de lógica entre `app/services/` e scripts `_tmp_*`/`deploy-*.sh`
- logs insuficientes em falhas de conector (OLT/RouterOS/câmera)

### Baixos
- organização do repositório (dezenas de scripts soltos na raiz, tarballs de deploy versionados)
- código morto, nomes confusos, documentação desatualizada (ex: `docs/STRUCTURE.md` descreve layout antigo `camsnapshot/`/`tools/` que não bate com `app/` atual)

## Prontidão para SaaS multi-cliente

Use esta seção quando o usuário perguntar se o sistema está pronto pra vender/escalar pra varios clientes, ou pedir pra corrigir fila/HTTPS/concorrência visando isso. Complementa (nao substitui) a skill generica `saas-scale-hardening` -- aqui e o que ja sabemos ESPECIFICAMENTE do SightOps, confirme se ainda procede antes de reportar.

Regra igual a sempre: correção mecânica de baixo risco pode ser aplicada direto; qualquer coisa estrutural (trocar fila em memória por fila de verdade, mudar modelo de dados, mexer no container `sightops-nginx` que serve produção) vira proposta de plano, nunca aplicada sozinha.

### 1. Isolamento entre tenants (o mais crítico pra vender)
- **Já achamos um bug real disso**: `app/services/connector_service.py` usava `data/connectors.json` global (sem `tenant_slug`), e o `GET /api/connectors/{id}` devolvia o token do conector sem checar role — um cliente conseguia ver/sequestrar o conector RouterOS de outro. Confirme se isso já foi corrigido; se não, é bloqueador pra vender.
- Padrão correto já usado em outras partes do sistema (`inventory_json.py`): `get_current_tenant_slug()` + `tenant_scoped_path()`. Qualquer serviço novo que grava arquivo, lista dado ou faz cache **precisa** passar por isso — grep por `DATA_DIR /` ou caminho fixo dentro de `app/services/*.py` sem passar por `tenant_scoped_path` é sinal de alerta.
- Rate limit do Gemini (`gemini_video_search.py`, criado nesta sessão) é hoje **global**, não por tenant — um cliente pesado consome o limite de chamadas de todos os outros. Antes de vender pra múltiplos clientes reais, isso precisa virar por-tenant.
- Qualquer cache em memória do processo (dict global, variável de módulo) que guarda dado sem chave de tenant é o mesmo bug em potencial.

### 2. Filas e jobs em background
- `app/api/endpoints/ia.py` (`_SEARCH_EXECUTOR`, `_SEARCH_JOBS`) e o padrão análogo em `connectors.py`/antigo `_INDEX_JOBS`: são `ThreadPoolExecutor` + dict em memória do próprio processo Python. Funciona com **uma única instância** da API. Se um dia rodar 2+ réplicas da `sightops-api` atrás de um load balancer, um cliente pode cair numa réplica que não tem o job dele (404 "busca não encontrada"), e um restart do container perde todo job em andamento sem aviso.
- Isso não precisa ser corrigido agora (o sistema roda 1 instância hoje), mas é o primeiro item que quebra ao tentar escalar horizontalmente — vale deixar registrado como "bomba-relógio conhecida" em vez de bug escondido.
- Verificar se algum job pesado não tem timeout (trava a thread do executor pra sempre se o DVR/API externa nunca responder).

### 3. HTTPS / TLS
- Estado em produção (10.10.12.7): há um container `sightops-tls` (nginx:alpine, porta 443, certificado de CA interna) na frente do `sightops-nginx` original (porta 80, sem TLS). **HTTP e HTTPS funcionam em paralelo hoje, sem redirecionamento forçado** — confirme se isso mudou antes de reportar.
- `sightops-nginx` (o container original, porta 80) **não tem volume/bind mount em `/usr/share/nginx/html/v2`** — todo o frontend deployado nesta sessão vive só na camada gravável do container. **Nunca rodar `docker compose up`/recreate nesse container sem antes confirmar que o frontend atual foi persistido em algum lugar (imagem nova publicada, ou bind mount configurado)** — o risco real é perder todo o trabalho de frontend silenciosamente ao recriar.
- Certificado da CA interna está em `/home/central/sightops-ca/` no servidor (fora do container, não versionado) — se precisar regenerar/expandir (novo domínio, SAN adicional), os arquivos-fonte estão lá.

### 4. Concorrência e limites
- `recorder_media_service.download_dav`/`download_clip_mp4`: cada busca de IA-NVR baixa um `.dav` e roda `ffmpeg` de forma síncrona dentro do request. Sob picos (vários clientes buscando ao mesmo tempo), isso empilha processos ffmpeg e downloads simultâneos sem limite — verificar se existe (ou falta) um teto de concorrência.
- Nenhum endpoint público tem rate limit próprio (fora o limitador do Gemini) — confirme se algum endpoint caro (scan, varredura, ia/nvr/search) pode ser chamado em loop por um cliente sem controle.

### 5. Multi-cliente na prática (contas, billing, limites)
- Confirme se existe hoje algum conceito de **plano/quota por cliente** (limite de câmeras, limite de buscas de IA por mês, limite de storage de clipes) ou se é tudo ilimitado — pra vender como SaaS de verdade isso normalmente é esperado, mesmo que rudimentar no início.
- Verificar se a criação de um tenant novo é um processo manual (script tipo `migrate_incoforte_tenant.py`) ou se já existe self-service — isso define se "vender pra mais gente" hoje significa "eu mexo no servidor pra cada cliente novo" (não escala) ou já é automatizável.

## Saída obrigatória

# Relatório de Auditoria SightOps

## Resumo executivo
- Estado geral:
- Mudanças recentes — o que fazem e se são seguras:
- Risco principal:
- O que corrigir primeiro:

## Mudanças analisadas
| Arquivo | O que mudou | Consistente com o resto do sistema? | Risco |
|---|---|---|---|

## Mapa do sistema
- Frontend:
- Backend/API:
- Banco:
- Streaming/conectores:
- Infra/Docker:

## Bugs encontrados
| Severidade | Área | Arquivo/Linha | Problema | Impacto | Correção |
|---|---|---|---|---|---|

## Bugs críticos detalhados
Para cada um: evidência, por que acontece, como reproduzir, correção recomendada.

## Prontidão para SaaS multi-cliente
- Veredito honesto: pronto / quase pronto / não pronto pra vender pra múltiplos clientes agora, e por quê.
- Isolamento entre tenants:
- Filas/jobs:
- HTTPS/TLS:
- Concorrência/limites:
- Multi-cliente na prática (quotas, criação de tenant):

## Testes e comandos executados

## Plano de correção
1. Correções imediatas
2. Correções de curto prazo
3. Melhorias estruturais

## Perguntas em aberto

## Regras de segurança
- Nunca exponha valores reais de `.env`, tokens, chaves privadas (`_tmp_sightops_deploy_ed25519`) ou senhas. Se encontrar segredo, informe arquivo e tipo, mas mascare o valor.
- Não rode comandos destrutivos, não apague dados, não rode migrations em produção, não faça `git push`/deploy sem confirmação do usuário.
- Não instale dependências sem necessidade.

## Comandos úteis

```bash
git -C "C:\PROJETOS\cam-snapshot-web-v2" status
git -C "C:\PROJETOS\cam-snapshot-web-v2" diff
git -C "C:\PROJETOS\cam-snapshot-web-v2" log --oneline -30
grep -RIn "TODO\|FIXME\|HACK\|password\|secret\|token\|api_key" app frontend --exclude-dir=node_modules
python -m compileall app
docker compose -f docker-compose.platform.yml config
```

Para o frontend (dentro de `frontend/`):

```bash
npm run lint
npm run build
```
