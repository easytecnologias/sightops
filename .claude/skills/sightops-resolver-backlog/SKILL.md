---
name: sightops-resolver-backlog
description: Resolve os itens de docs/backlog-produto.md (seguranca, avisos, erros, primeiro acesso, desempenho, LGPD, celular) com varios agentes em paralelo, cada um numa copia isolada (worktree) e dono de uma frente. Integra, roda os revisores de isolamento e Zabbix, testa e deixa commitado local -- nao publica nem da push. Use quando o usuario pedir para "resolver o backlog", "resolver tudo da analise", "corrigir os achados", ou citar IDs (S1, A3...) ou frentes do backlog.
---

# Resolver o backlog com varios agentes

O backlog (`docs/backlog-produto.md`) e a fonte. Cada item tem ID, faixa,
frente e estado. Esta skill **conserta e commita local**. Publicar e com
`/sightops-publicar` (o usuario dispara); push e do usuario.

Responda ao usuario em portugues, curto, em linguagem de dono de negocio.

## Faixas (decisao do usuario, nao reabrir)

- **verde**: o agente faz, testa e commita sem perguntar.
- **amarelo**: o agente **so planeja** na 1a rodada. Voce mostra os planos ao
  usuario (AskUserQuestion, um por item ou agrupado), e so os aprovados vao para
  a 2a rodada. Mudanca que tira algo do cliente nasce desligada ou em modo aviso.
- **vermelho**: nunca. Liste no relatorio como "precisa de voce".

## 1. Escopo

Argumento do usuario: IDs (`S1 A3`), frentes (`S A`), faixa (`verde`) ou nada.
Sem argumento = todos os itens **verdes** em estado `aberto`, e os amarelos so
na rodada de planejamento.

## 2. Conferir antes de abrir agente (voce, nao os agentes)

1. `git status` limpo e `git fetch servidor`; se `main` estiver atras de
   `servidor/main`, pare e rode `/sightops-sincronizar` antes.
2. **Producao x git** dos arquivos das frentes escolhidas (producao nao vem do git):
   ```bash
   ssh sightops 'docker exec sightops-v3-api sh -c "cd /app && md5sum app/core/security.py app/main.py ..."'
   md5sum app/core/security.py app/main.py ...
   ssh sightops 'cd /home/central/sightops-v3-release/frontend && md5sum index.html js/core.js ...'
   ```
   Arquivo divergente: o item dele fica `parado: producao diverge do git` ate
   sincronizar. Nunca deixe o agente corrigir sobre a versao velha do git.
3. Leia a memoria `sessoes-paralelas`: se outra sessao mexe nos mesmos arquivos
   ou no `?v=`, combine com o usuario antes.
4. Marque os itens escolhidos como `em andamento (<frente>)` no backlog (commit
   so do backlog).

## 3. Disparar as frentes NUMA UNICA mensagem

Uma chamada Agent por frente com itens no escopo, todas na mesma mensagem:
`subagent_type: "general-purpose"`, `isolation: "worktree"`. Frentes e o que
cada uma e dona:

| Frente | Itens | Arquivos principais |
|---|---|---|
| S Seguranca | S1-S8 | `app/core/security.py`, `tools.py` (backup), `auth.py`, `auth_store.py` (S7), `maintenance.py` (proxy web), webhook Meta |
| R Rede entre clientes | R1-R4 | `network_tools.py`, `ws.py`, `connector_routing_vnat.py`, `olt.py`, `models/requests.py`, `cli/tools/olt_*`, `helpers.js` |
| A Avisos | A1-A8 | `app/main.py` (loops), `zabbix_monitoring_service.py`, `monitoring_service.py`, `telegram_notification_service.py`, `alert_store.py`, `alert.py` |
| E Erros e suporte | E1-E9 | `app/core/erros.py` (novo), `core.js`, `index.html` (login e textos), `bootstrap.js` (mensagens), `settings.py` |
| P Primeiro acesso/plano | P1-P7 | `dashboard.js`, `permissions.py`, `licensing_service.py`, `auth_store.py` (catalogo), `connectors.js`, menu do `index.html` |
| D Desempenho | D1-D7 | `alert.js`, `cameras.js`, `cameraActivation.js`, `rede.js`, `maquete.js`, `bootstrap.js` (lotes), `accessControl.js`, `cameras.py` |
| L LGPD | L1-L7 | `access_control_*.py`, `historico_service.py`, migrations novas |
| M Celular | M1-M4 | `mobile/` |

Arquivo de duas frentes (`main.py`, `bootstrap.js`, `index.html`,
`auth_store.py`, `security.py`) e normal: o git junta trechos diferentes. Por
isso a regra de diff minimo abaixo e obrigatoria.

### Prompt de cada frente (preencha os <>)

```
Voce e a frente <X> do backlog do SightOps (repo nesta worktree). Itens: <IDs e linhas do backlog copiadas>.
Rodada: <IMPLEMENTAR verdes | PLANEJAR amarelos | IMPLEMENTAR amarelos aprovados: <plano aprovado>>.

Leia CLAUDE.md e docs/backlog-produto.md. Regras:
- Confira a linha citada antes de mexer; se o problema nao existe mais, devolva "ja resolvido" com a prova.
- Diff minimo: nao reformate, nao reordene, nao renomeie fora do item. Nao suba ?v= no index.html (o integrador sobe).
- Nao use ssh, nao fale com equipamento, nao rode nada contra producao. Nao teste save_person com pessoa real.
- Isolamento: todo dado gravado/lido passa por tenant_scoped_path/get_current_tenant_slug; cache com chave de tenant.
- Rota de escrita nova precisa entrar em _role_rules (app/core/security.py).
- Recurso de monitoramento so esta pronto quando chega ao Zabbix.
- Sem except mudo: toda falha nova vira logger.warning com contexto.
- Cada item ganha teste em tests/ que falha antes e passa depois (quando o item for backend).
- Verifique: python -m compileall -q app && python -c "import app.main"; python -m pytest tests -q; node --check em cada .js mexido.
- Um commit por item, mensagem "fix(<frente>): <ID> <frase>" terminando com
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
- Rodada PLANEJAR: nao edite nada; devolva por item: o que muda para o cliente, arquivos, migration (sim/nao), como desligar, risco.

Devolva: por item -> feito (commit) | ja resolvido | parado (motivo); saida dos testes (numeros); o branch da worktree;
arquivos compartilhados que tocou; o que precisa de decisao do usuario.
```

## 4. Integrar (voce)

1. Ordem de merge no `main` local: **S, R, A, E, P, D, L, M** (seguranca primeiro).
   Conflito: resolva mantendo as duas intencoes; na duvida, pergunte.
2. Frontend mexido: suba o `?v=` de cada JS/CSS alterado **uma vez**, com numero
   inedito (maior que todos no `index.html`; o hook `checar_edicao.py` confere).
3. Rode os revisores em paralelo sobre o diff integrado:
   - `revisor-isolamento` (frentes S, R, A, P, L e qualquer `app/services`, `app/api/endpoints`, `app/core`);
   - `revisor-zabbix` (frentes A e P4).
   Achado confirmado volta para a frente dona (SendMessage) ou voce corrige, e roda de novo.
4. Verificacao final no `main` integrado: compileall, `import app.main`,
   `pytest tests -q`, `node --check` dos JS mexidos. Falhou: nao diga pronto.
5. Atualize o estado no backlog (`feito <commit>` / `parado: <motivo>`) num commit
   `docs(backlog): estado apos rodada <data>`. Remova as worktrees sem uso.

## 5. Relatorio ao usuario

Comece pelo resultado, frases curtas:
- quantos itens feitos / ja resolvidos / parados, por frente;
- o que muda para o cliente quando publicar (1 linha por item visivel);
- planos amarelos esperando aprovacao (se a rodada foi de planejamento);
- vermelhos que precisam dele (S9, L8, P8, preco);
- numeros dos testes antes/depois.

Termine com: "Para colocar no ar: `/sightops-publicar`. Depois, conferir em
producao: <1 prova por item, ex.: admin de cliente toma 403 em /api/backup/export>."
Nao publique, nao de push, nao recrie container.
