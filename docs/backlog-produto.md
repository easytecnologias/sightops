# Backlog de produto e seguranca — SightOps v3

Fonte unica para a skill `/sightops-resolver-backlog`. Junta a analise de
produto (11 agentes, 05/11/2026) e a de seguranca (`docs/analise-2026-11-05.md`).
Cada item tem: **ID**, **faixa**, **frente** (agente dono), **arquivos** e **estado**.

Faixas:
- **verde** — codigo, teste e commit local sem perguntar.
- **amarelo** — muda o que o cliente ve ou o banco: o agente escreve o plano,
  o usuario aprova, depois faz. Nasce desligado ou em modo aviso quando der.
- **vermelho** — nunca pela skill: decisao comercial, equipamento vivo,
  servidor (sshd, segredos, nginx do host), publicar, push.

Estados: `aberto` · `em andamento (<frente>)` · `feito <commit>` · `publicado <tag>` · `parado: <motivo>`.
Ao terminar um item, o integrador troca o estado aqui no mesmo commit.

Prova citada e da leitura do codigo em 05/11; **confira a linha antes de mexer**
(o arquivo pode ter mudado e producao pode estar diferente do git).

---

## Frente S — Seguranca critica (`security.py`, rotas de admin)

| ID | Faixa | Problema | Onde | Correcao | Estado |
|---|---|---|---|---|---|
| S1 | verde | Qualquer logado baixa ZIP com `data/` de TODOS os clientes (chaves WireGuard) | `app/api/endpoints/tools.py:1495`, `app/core/security.py:53` | Export e import so `is_platform_admin`; tirar `/api/backup/export` de `_query_token_paths`; teste de 403 para admin de cliente | aberto |
| S2 | verde | Admin de cliente apaga o banco de todos (`/api/db/storage/migrate`, `/api/auth/storage/migrate` com force, `/api/db/init`, `/api/db/migrate`, `/api/system/bootstrap`) | `security.py:90`, `database.py:59-70`, `db_store.py:701`, `auth.py:856` | Exigir `is_platform_admin` | aberto |
| S3 | verde | Viewer abre porta/reinicia pelo proxy web com GET | `security.py:139,396`, `maintenance.py:2431-2487` | `/api/maintenance/web/` exige operator em qualquer metodo | aberto |
| S4 | verde | Proxy web roda HTML da camera na origem do painel (rouba agent-token, repassa Set-Cookie) | `maintenance.py:2433-2563`, `auth.py:393-399` | `Content-Security-Policy: sandbox` nas respostas do proxy; descartar Set-Cookie | aberto |
| S5 | verde | Limite de login burlado por X-Forwarded-For | `auth.py:209`, `alert.py:62` | IP de `CF-Connecting-IP`/ultimo salto confiavel; limite tambem por usuario | aberto |
| S6 | verde | Webhook Meta sem App Secret aceita POST forjado | `access_control_notifications.py:285-291`, `access_control.py:436-517` | Fail-closed sem segredo; conferir dono do `phone_number_id` x tenant | aberto |
| S7 | verde | Owner do tenant default troca senha do admin da plataforma | `auth_store.py:1204` | Bloquear alteracao de `is_platform_admin` por quem nao e | aberto |
| S8 | amarelo | `/api/auth/status` (publica) roda migrations a cada chamada; `/health/ready` vaza host do banco | `auth.py`, health | Migration so no startup; health sem detalhes | aberto |
| S9 | vermelho | `APP_ENV: homologation` no compose pode criar `admin_teste`; segredos no ENV da imagem; Grafana com usuario completo; sshd | `docker-compose.production.yml:8`, `deploy/imagem/achatar-imagem.sh:55-62` | Servidor e segredos: so o usuario | aberto |

## Frente R — Rede entre clientes (vnat, OLT)

| ID | Faixa | Problema | Onde | Correcao | Estado |
|---|---|---|---|---|---|
| R1 | verde | Cliente A alcanca rede do B pelo IP virtual (network tools, ws/portscan, ws/snapshot, stream, lotes de senha/NTP/IP) | `network_tools.py:227-331`, `ws.py:316-466`, `connector_routing_vnat.py:132-188`, `maintenance.py:283-287,1812,3430` | Funcao unica `destino_permitido(tenant, ip)`: recusa `virtual_cidr` de outro tenant, loopback, Docker, link-local; exige dono do IP | aberto |
| R2 | verde | OLT sem `olt_id` cai na OLT de outro cliente | `olt.py:112` | `olt_id` obrigatorio e do tenant | aberto |
| R3 | verde | Quebra de linha em descricao/serial/profile vira comando na OLT | `app/cli/tools/olt_8820i_add_onu.py:169,475,585`, `app/models/requests.py:150` | Regex no modelo; `cli_run` recusa `\r\n` | aberto |
| R4 | verde | `esc()` nao escapa aspas simples em `onclick='...'`; popup do mapa sem escape | `frontend/js/helpers.js:46`, `cameras.js:2077-2120`, `deploy.js:3753` | Escapar `'`; montar popup com textContent | aberto |

## Frente A — Avisos que chegam (monitoramento, Zabbix, panico)

| ID | Faixa | Problema | Onde | Correcao | Estado |
|---|---|---|---|---|---|
| A1 | verde | Erro do Zabbix ou de 1 cliente cala os avisos de todos | `app/main.py:310-334`, `zabbix_monitoring_service.py:661-665` | try por cliente e por etapa; Telegram roda mesmo com Zabbix falhando; gravar erro em `monitoring_refresh_last` | aberto |
| A2 | verde | Acima de 2000 entidades do tipo, hosts sao apagados do Zabbix | `monitoring_service.py:973`, `zabbix_monitoring_service.py:683-697`, `telegram_notification_service.py:128` | Paginar; nunca apagar orfao quando a lista bateu no limite | aberto |
| A3 | verde | Panico so avisa apos 60 s, tenta 1 vez, marca enviado antes | `alert.py:463-467`, `alert_store.py:44,1463-1490` | Avisar no disparo; campo de entrega; retry com espera crescente; selo "nao entregue" na central | aberto |
| A4 | verde | Falha ao descobrir site do conector no panico: `except: pass`, vai para grupo errado/nenhum | `alert_store.py:1424-1446` | Log + aviso na prontidao do membro sem grupo | aberto |
| A5 | verde | Configuracao de acao/grupo no Zabbix falha calada | `zabbix_monitoring_service.py:476-478,723-724,779-781` | `logger.warning` + contagem de falhas no resultado do sync, exibida na tela | aberto |
| A6 | verde | Aviso para varios grupos: 1 entregue marca todos | `telegram_notification_service.py:261-274` | Estado por grupo; retry so dos que falharam | aberto |
| A7 | amarelo | "Sem informacao" e coleta parada nao geram aviso; OLT/ONU nunca expiram | `monitoring_service.py:212,544-609`, `telegram_notification_service.py:141-148`, `main.py:285-287` | Evento "sem dados ha X min" por site; erro de sync em warning | aberto |
| A8 | amarelo | Panico e queda so por Telegram | `alert_store.py:1436-1450`, `access_control_notifications.py` | WhatsApp/e-mail como destinos do `notificacoes_service` | aberto |

## Frente E — Erros, suporte e primeira impressao

| ID | Faixa | Problema | Onde | Correcao | Estado |
|---|---|---|---|---|---|
| E1 | verde | Login vem com "elishafan" preenchido; subtitulo "Gestao de CFTV" | `frontend/index.html:22,30` | Tirar `value`; placeholder neutro | aberto |
| E2 | verde | "Internal Server Error" e "[object Object]" na tela | `app/main.py:114`, `frontend/js/core.js:312-316` | Handler de `Exception` com codigo (request_id) e de 422 em portugues; `core.js` junta lista de `detail` | aberto |
| E3 | verde | Erro de equipamento chega cru (HTTPConnectionPool...) ou vira pagina do Cloudflare | `main.py:105-118`, `dvr.py`, `playback.py`, `deployments.py`, `windows.py` | 502/504 -> 424 em todo `/api/`; tradutor de erro de rede para frase com proximo passo | aberto |
| E4 | verde | Acentos quebrados ("informa--es", "NAo foi possAvel", "Carregando-") e menu sem acento | `frontend/index.html:61-180,312-352,1266,4135,4233`, `bootstrap.js:717`, `cameras.js:3990` | Revisao de texto + checagem no hook | aberto |
| E5 | verde | Saida de Zabbix/Grafana mostra stderr/JSON cru | `bootstrap.js:1884-1999` | Resumo legivel + "ver detalhes" | aberto |
| E6 | verde | Historico mostra JSON tecnico | `frontend/js/core.js:1144` | Frase por tipo de acao | aberto |
| E7 | verde | Versao fixa 1.1.0 | `app/core/settings.py:71` | Ler da tag da imagem (`CAM_SNAPSHOT_IMAGE`/env no build) | aberto |
| E8 | amarelo | Sem "Esqueci a senha" | `index.html:28-36`, `auth.py` | Link por e-mail (SMTP ja existe) com token curto | aberto |
| E9 | amarelo | Conector offline sem diagnostico | `connectors.js:100-110`, `connector_service.py:460-479` | Pagina de passos verde/vermelho (cadastro, heartbeat, handshake, gateway, equipamento) | aberto |

## Frente P — Primeiro acesso e plano

| ID | Faixa | Problema | Onde | Correcao | Estado |
|---|---|---|---|---|---|
| P1 | verde | Painel vazio diz "Sem pendencias: OK" | `frontend/js/dashboard.js:418-464` | Checklist "Primeiros passos" quando 0 conector/0 equipamento | aberto |
| P2 | verde | Conector escondido no fim do menu; "Cameras IP" 4 vezes | `frontend/index.html:61-121` | Conectores no topo; nomes distintos (Instalar / Lista / Fotos / Manutencao) | aberto |
| P3 | verde | PDV fora do `MODULE_CATALOG` (cliente restrito nunca recebe) | `auth_store.py:685-722` | Incluir telas `pdv-*`, `alert-reports`, `access-painel` | aberto |
| P4 | verde | `pdv`, `link`, `switch_provedor` sem peso/rotulo na licenca | `licensing_service.py:37-49,150,166` | Declarar em `ENTITY_TYPES` com peso **a decidir** (padrao proposto: link 0, switch_provedor 0, pdv 1) | aberto |
| P5 | amarelo | Plano nao liga modulos; `enabled_modules` NULL libera tudo | `permissions.py:259-266`, `auth_store.py:494,743-773` | Plano ganha `modulos`; efetivo = plano ∩ ajuste. **Clientes atuais nao perdem nada** (migrar para lista explicita igual ao que tem hoje) | aberto |
| P6 | amarelo | Teste de 14 dias nao vence; limite de usuarios nao vale | `licensing_service.py:12-13,54,217` | Cliente novo nasce no Teste com data fim; "faltam X dias"; vencido = so leitura; `user_limit` barra criar usuario | aberto |
| P7 | amarelo | Assistente do conector (roteador -> comando -> aguardando -> varrer) | `connectors.js:692-697`, `index.html:4287-4336` | Wizard de 3 telas + varredura automatica ao ficar online | aberto |
| P8 | vermelho | Autocadastro publico ("Teste gratis") | `auth_store.py:477` | Depende de decisao comercial | aberto |

## Frente D — Desempenho percebido

| ID | Faixa | Problema | Onde | Correcao | Estado |
|---|---|---|---|---|---|
| D1 | verde | Alerta consulta a cada 1,5 s em toda aba | `frontend/js/alert.js:44,578-591` | Resumo a 10 s (sirene segue 1,5 s com alerta aberto) | aberto |
| D2 | verde | Lista de cameras pedida 3x em serie com `_=Date.now()` | `cameras.js:765`, `cameraActivation.js:596`, `rede.js:383`, `maquete.js:520`, `dashboard.js:229` | `Promise.all`; tirar cache-buster | aberto |
| D3 | verde | "Capturar selecionadas"/"Atualizar todas" sem progresso; "todas" da 404 calado | `bootstrap.js:1013-1027`, `cameras.js:853-971` | Usar `/api/cameras/snapshot/capture` com concorrencia 4 e "X de N" | aberto |
| D4 | verde | "Ping selecionados" sem retorno; "Atualizar ImgBB" sem selecao manda todas (8 min) | `bootstrap.js:514-692` | Botao ocupado; resultado na linha; confirmar envio de todas | aberto |
| D5 | verde | Apagar/sincronizar pessoas uma a uma | `accessControl.js:2639-2690` | Concorrencia 4-6 + contador | aberto |
| D6 | amarelo | `/api/cameras` remonta tudo e checa 4 caminhos por camera | `cameras.py:284-439`, `photo_store.py:47-73` | Cache por tenant invalidado no save; indice de snapshots | aberto |
| D7 | amarelo | 50 scripts sem `defer` na entrada (2,6 MB) | `frontend/index.html:8157-8212` | Carregar por view; Leaflet/lucide locais | aberto |

## Frente L — LGPD

| ID | Faixa | Problema | Onde | Correcao | Estado |
|---|---|---|---|---|---|
| L1 | verde | Foto da passagem por e-mail abre sem login por 7 dias | `access_control_email.py:48,533`, `security.py:238-241` | 24 h; registrar abertura; opcao de desligar foto | aberto |
| L2 | verde | Excluir pessoa deixa foto facial e passagens | `access_control_store.py:624-632`, `access_control_photos.py:41-46` | Apagar foto; anonimizar `access_events`; registrar eliminacao | aberto |
| L3 | amarelo | Sem prazo de guarda (passagens, posicoes, eventos PDV) | `historico_service.py:26` e tabelas | Prazo por cliente/tipo + tarefa diaria; **comeca desligado** | aberto |
| L4 | amarelo | Sem 2FA | `auth_store.py:1335-1366` | TOTP; obrigatorio para admin de plataforma | aberto |
| L5 | amarelo | Sem registro de quem viu dado pessoal | `historico_service.py:1-6` | Registrar leitura de foto, ficha, backup, posicoes | aberto |
| L6 | amarelo | Dado de aluno sem consentimento/base legal | `019_rotas_cadastro.sql:84-100`, `access_control_store.py:138-170` | Migration com campos de base legal/consentimento | aberto |
| L7 | amarelo | Exportacao por titular | `access_control_dados.py` | Relatorio por CPF de todos os modulos; CPF mascarado na lista | aberto |
| L8 | vermelho | Backup sem criptografia e no mesmo servidor | `deploy/backup/sightops-backup.sh` | Servidor: so o usuario | aberto |

## Frente M — Celular (`mobile/`)

| ID | Faixa | Problema | Onde | Correcao | Estado |
|---|---|---|---|---|---|
| M1 | verde | App do dono (PDV) nao pede PIN | `mobile/dono/src/lib/api.ts` | Reaproveitar `pin.ts` do rua | aberto |
| M2 | amarelo | Panico nao se atende pelo app do tecnico | `mobile/rua/src/telas/Alertas.tsx:80-86` | Botoes Visto/A caminho/Encerrar com PIN (API ja existe) | aberto |
| M3 | amarelo | Sem push | apps + backend | FCM; tabela de aparelhos; mesmos eventos do Telegram | aberto |
| M4 | amarelo | Biometria nos 3 apps | `mobile/*` | Biometria com PIN de reserva | aberto |

## Fora da skill (grande ou depende de decisao/equipamento)

Cobranca Asaas · white-label · conta de revenda · API com chave e webhook ·
IXC · drivers Huawei/ZTE (exige OLT real) e corrigir README (verde, pode entrar) ·
Control iD · condominio (unidade/morador/visitante) · GPS e medicao do transporte ·
NFC-e no PDV · cota da IA por cliente · iOS/PWA · Excel nas listas · tabelas em
cartao no celular · preco (OLT/ONU, Escola Segura, adicionais por unidade, faixa > 250).
