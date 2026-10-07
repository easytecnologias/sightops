---
name: sightops-auditar-estado
description: >-
  Audita item a item se o que o SightOps MOSTRA sobre o estado do parque e
  verdade — dashboard, cards, Zabbix, OLT, ONU, gravadores, conectores e
  telemetria. Use sempre que o usuario disser que a tela mostra informacao
  velha, errada ou que "nunca funciona"; que algo caiu e o sistema continuou
  dizendo online; que ele descobriu um problema sozinho em vez de ser avisado;
  que a telemetria so funciona quando ele roda na mao; ou que rodar a
  telemetria APAGA dados. Tambem use antes de prometer a um cliente que o
  SightOps avisa quando algo cai, e quando pedirem para "conferir o Zabbix" ou
  "ver por que o card esta errado". Gatilho forte: "mostra online e esta
  offline", "informacao velha", "nao fui avisado", "o conector caiu e a OLT
  continua verde".
---

# Auditar o estado que a tela mostra

Um sistema de gestao de CFTV vale pelo que ele te conta quando voce **nao**
esta olhando. Se a tela diz "online" sobre um equipamento que caiu ontem, ela
e pior que uma tela vazia: a vazia manda voce ir conferir, a mentirosa manda
voce dormir.

Esta skill existe porque isso ja custou caro. Em 28/09/2026 o conector de
SANTANA caiu e o SightOps seguiu mostrando todas as cameras online. O usuario
so descobriu quando tentou usar o sistema:

> "O CONECTOR DE SANTANA CAIU E AS CAMERAS AINDA MOSTRAM ONLINE O CONECTOR
> MOSTRA ONLINE TUDO SENDO QUE PERDI O ACESSO TODO PQ O SISTEMA NAO MOSTROU
> NADA"

A correcao daquele dia criou `app/services/status_efetivo.py`, que faz duas
perguntas honestas antes de repetir um status guardado: **ha quanto tempo isso
foi medido?** e **a fonte da medicao ainda esta de pe?**. Se a leitura
envelheceu ou o conector caiu, o status vira `unknown` — "nao verificado" —
nunca `down`, porque o sistema nao sabe se caiu; sabe que nao sabe.

O problema que esta skill persegue: **esse remedio foi aplicado em camera e
parou ali**.

## O estado da doenca (conferido em 05/10/2026)

| Mostra status de | Usa `status_efetivo`? |
|---|---|
| `app/api/endpoints/cameras.py` | sim |
| `app/services/dashboard_service.py` | sim |
| `app/services/monitoring_service.py` | sim |
| `app/api/endpoints/olt.py` | **nao** |
| `app/api/endpoints/nvr.py` | **nao** |
| `app/api/endpoints/dvr.py` | **nao** |

E por isso que o conector cai e a OLT continua verde, e que a camera aparece
offline na tela de cameras enquanto o canal dela no gravador segue "normal".
Nao e um bug por tela: e a mesma doenca em lugares que ninguem tratou.

Confira se isso ainda vale antes de repetir — o mapa envelhece:

```bash
cd /home/central/sightops-v3
grep -rln 'status_efetivo' app/ --include=*.py
```

## As tres perguntas

Para **cada numero e cada bolinha colorida** da tela, pergunte:

1. **De onde vem?** Medicao ativa agora, leitura guardada, ou derivado de outra
   coisa? Status guardado sem carimbo de tempo nao e informacao, e lembranca.
2. **Quando foi medido?** Se o dado nao carrega "medido as HH:MM", a tela nao
   tem como saber se envelheceu — e vai repetir o ultimo valor para sempre.
3. **O que acontece quando a fonte cai?** Conector offline, OLT inacessivel,
   gravador sem senha. A resposta certa e "vira nao verificado". A resposta
   errada, e a comum, e "continua mostrando o ultimo valor bom".

Uma quarta, que o usuario cobra com razao: **onde ele e avisado?** Um estado
correto que so existe dentro de uma tela que ninguem abriu nao serve para
gestao.

## Auditoria item a item

Percorra nesta ordem. Nao pule — cada item ja escondeu um problema diferente.

### 1. Conectores (a raiz de tudo)

O conector e a fonte de quase todo dado remoto. Se ele cai, **tudo atras dele
fica desconhecido** — cameras, OLT, gravador, switch.

- O status do conector vem do handshake do `wgc` (liveness do provisioner), nao
  de ping. Confirme que o "online" dele e recente, nao herdado.
- Liste quantos estao online e ha quanto tempo foi o ultimo contato:

```bash
docker exec -e PYTHONPATH=/app -w /app sightops-v3-api python -c "
from app.core.tenant_context import set_current_tenant_slug
from app.services.connector_service import list_connectors
for slug in ('rads','inforbr','easy-tecnologias'):
    set_current_tenant_slug(slug)
    for c in list_connectors().get('connectors', []):
        print(slug, c['name'], c.get('status'), 'visto em', c.get('last_seen'))
"
```

**O que procurar:** conector com `last_seen` velho e status `online`. Isso e a
mentira na raiz — toda tela abaixo dele vai repetir.

### 2. Cameras IP

Aqui o remedio esta aplicado. Confira que continua ligado e que o limite de
idade faz sentido para o parque:

- `status_efetivo.LIMITE_LEITURA_MIN` (padrao 30 min, env
  `SIGHTOPS_LEITURA_VALIDA_MIN`).
- Na tela, camera sem leitura recente aparece como **"nao verificado"**, com o
  motivo. Se aparecer "online" sem carimbo, o `aplicar_em_linha` nao esta sendo
  chamado naquele caminho.

### 3. Gravadores e seus canais

Dois estados diferentes que a tela costuma misturar:

- **O gravador responde?** (nos alcancamos ele)
- **O canal tem imagem?** (ele alcanca a camera)

Os dois podem discordar, e discordam: na TELHA, em 02/10/2026, o canal 14
estava `online: true` no NVR enquanto a camera dele nao existia para a rede do
site (entrada ARP sem MAC). O inverso tambem: o canal 01 `online: false` com a
camera respondendo normalmente.

**Nao "conserte" essa divergencia escondendo um dos lados.** Os dois sao
verdade, de pontos de vista diferentes, e a diferenca entre eles e justamente o
diagnostico. Mostre os dois.

### 4. OLT e ONU

- O status da OLT nao passa pelo `status_efetivo`: confirme o que acontece com
  ela quando o conector dela cai.
- **ONU que cai some do inventario** em vez de aparecer caida — ver
  `[[onu-down-some-do-inventario]]`. Sumir e pior que ficar vermelho: o
  equipamento desaparece da gestao exatamente quando precisa de atencao.
- Em conector isolado a OLT so responde no **IP virtual (vnat)**. Um teste
  contra o IP real devolve "No route to host" e vira "offline" mentiroso — ver
  `[[sightops-olt-ip-real-nao-alcanca]]`.

### 5. Zabbix

O Zabbix e uma segunda opiniao, nao a verdade. Ele ja marcou **um cliente
inteiro como offline** porque a validacao TCP sondava o IP real em vez do
virtual (`[[sightops-zabbix-status-sync-conector]]`).

Confira:
- Cada camera tem **dois** hosts (medicao e telemetria) — ver
  `[[sightops-apagar-camera-limpa-zabbix]]`. Host orfao de camera apagada
  continua alarmando sobre equipamento que nao existe.
- A senha do Zabbix salva no banco **vence a do ambiente** e envelhece. Zabbix
  "sem dados" costuma ser isso, nao falha de rede.
- Equipamento no inventario sem host no Zabbix = nunca vai alarmar. Compare as
  duas listas; o buraco e silencioso.

### 6. Cards do dashboard

Cada card e um numero somado de alguma lista. Para cada um, descubra **qual
lista** e **se ela passa pelo filtro de idade**:

- "Precisam de atencao" e util so se o criterio for explicito. Confira o que
  entra nessa conta.
- Card que conta "monitorados" (ONU, controladoras, computadores) tem que
  distinguir **nao monitorado** de **monitorado e sem resposta**. Sao coisas
  opostas e o numero sozinho nao diz qual e.
- Cartao com `0` de algo que existe no parque (ex.: WhatsApp 0, Computadores 0)
  e candidato a "nunca funcionou" — verifique se ha coletor rodando, antes de
  tratar como "esta tudo bem".

### 7. Onde o usuario e avisado

Estado certo sem aviso nao resolve gestao. Mapeie, por tenant:

- Telegram (`telegram_notification_service.py`) — habilitado? token valido?
- WhatsApp/Evolution — habilitado?
- `alert_store.py` / `zabbix_monitoring_service.py` — quem dispara, com que
  gatilho, e para quem.

**Em 02/10/2026 o alerta de queda estava desligado nos dois tenants
principais.** Era por isso que SANTANA passou despercebido: nao foi so a tela
mentir, foi nao existir caminho de aviso.

### 8. Telemetria: manual nao e telemetria

Se o usuario precisa clicar para saber se algo esta de pe, o sistema nao esta
monitorando — esta oferecendo uma consulta. Confira:

- Existe coleta **agendada** para OLT/ONU/gravador, ou so sob demanda?
- A coleta **apaga** o que a anterior gravou? E o caso conhecido do
  `collect_macs`, que sobrescreve o estado que a telemetria tinha escrito
  (`[[onu-down-some-do-inventario]]`). Sintoma classico: "rodei a telemetria e
  os dados sumiram".
- Coleta que falha em silencio e igual a coleta que nao existe. Ela registra o
  erro em algum lugar que alguem olha?

## Como reportar

O usuario quer decidir o que consertar primeiro. Entregue nesta forma:

```
## O que a tela esta dizendo de errado
Uma linha por achado, na lingua da operacao:
"Conector X caiu as 14:10 e as 23 cameras dele seguem verdes."
NAO: "olt.py nao chama aplicar_em_linha."

## Por que acontece
O mecanismo, em uma ou duas frases, com o arquivo/linha.

## O que isso custa
O que o usuario deixa de saber, e o que ja aconteceu por causa disso.

## Ordem sugerida
1. O que mente (status errado) -- mais grave: induz a decisao errada
2. O que falta avisar (sem alerta)
3. O que esta velho (sem carimbo de idade)
4. O que e cosmetico
```

Separe sempre **mentira** de **ausencia**. Mostrar "online" para algo caido e
muito pior do que mostrar "nao verificado": o primeiro faz o usuario ir embora
tranquilo, o segundo faz ele ir conferir.

## Erros que ja cometi aqui

**Inventar o estado para preencher a tela.** Quando a medicao nao da para ser
feita, a resposta honesta e "nao verificado". Chutar `down` tambem e mentira —
e gera chamado de campo para equipamento que esta funcionando.

**Confiar no `online` de um campo sem olhar o carimbo de tempo.** Status
guardado sem `checado_em` e lembranca, nao medicao. Se o campo nao existir,
esse e o achado.

**Tratar divergencia entre duas fontes como bug de uma delas.** Gravador diz
que o canal esta online e a rede diz que a camera nao existe: as duas estao
certas, e a diferenca e o diagnostico (a camera fala com o gravador por um
caminho que o roteador nao enxerga).

**Olhar so o que a tela mostra.** O buraco mais perigoso e o equipamento que
nao aparece em lugar nenhum — ONU que sumiu, camera sem host no Zabbix. Compare
listas, nao so valores.

**Consertar o sintoma na tela.** Pintar de cinza no frontend resolve a captura
de tela e nao resolve o alerta, o relatorio nem a API. O lugar certo e onde o
estado e decidido.

## Relacionado

`[[sightops-zabbix-status-sync-conector]]`, `[[onu-down-some-do-inventario]]`,
`[[sightops-olt-ip-real-nao-alcanca]]`,
`[[sightops-apagar-camera-limpa-zabbix]]`,
`[[sightops-telemetria-precisa-ser-automatica]]`,
`[[sightops-olt-enriquecimento-na-leitura]]`,
skills `sightops-bug-producao` e `sightops-conferir-servidor`.
