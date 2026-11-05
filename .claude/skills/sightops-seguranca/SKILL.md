---
name: sightops-seguranca
description: Teste de invasao autorizado do SightOps com 7 agentes em paralelo (autenticacao e sessao, autorizacao e isolamento entre clientes, injecao e SSRF, superficie publica sem login, segredos e infraestrutura, XSS e apps, e ataque pratico numa copia local). Tom duro, achados com prova e correcao. Use quando o usuario pedir "teste de seguranca", "pentest", "tenta invadir", "o que tem de vulneravel", ou antes de vender para prefeitura/escola. So le e ataca copia local; nunca producao.
disable-model-invocation: true
---

# Teste de seguranca com 7 agentes

## Regras para TODOS os agentes (copie no prompt de cada um)

- Teste AUTORIZADO pelo dono. Pense como atacante e seja duro: o dono quer
  critica, nao elogio.
- So leitura do repositorio. Nao editar, nao commitar.
- NUNCA acessar producao, o servidor do cliente, IP publico ou qualquer host
  externo; nada de ssh. Equipamento de cliente e vivo.
- Segredo encontrado: mostrar so os 4 primeiros caracteres e onde esta.
- Saida em portugues: ate 10 achados ordenados por gravidade, cada um com
  Gravidade (critico/alto/medio/baixo) | Como um atacante explora (passo a
  passo, que perfil precisa) | Prova (arquivo:linha com trecho) | Correcao |
  Esforco (pequeno/medio/grande). Sem prova, nao entra. Listar em 3 linhas o
  que esta correto. Fechar com nota 0-10.

## Disparar os 7 NUMA UNICA mensagem

Ferramenta Agent: tipo `Explore` para 1 a 6, `general-purpose` para 7.

| # | Agente | Onde olhar / o que tentar |
|---|---|---|
| 1 | Autenticacao e sessao | `app/services/auth_store.py`, `app/api/endpoints/auth.py`, `app/core/security.py`: geracao e guarda de token, revogacao, token em query string, rate limit e `X-Forwarded-For`, admin padrao/`APP_ENV`, agent-token, links assinados, ativacao do app de panico, token do PDV, auth do WebSocket |
| 2 | Autorizacao e isolamento | Varrer `app/api/endpoints/*.py`: IDOR, rota sem dono conferido, GET com efeito colateral, `_role_rules`, modo "sombra" de `app/core/permissions.py`, rotas que exigem so "admin" mas afetam a plataforma, cache sem chave de tenant, IP virtual de conector de outro cliente |
| 3 | Injecao e SSRF | grep por `subprocess`, `shell=True`, `execute(f`, `.format(`, `open(`, `extractall`, `pickle`, `yaml.load`, `eval`; comandos para OLT/RouterOS com `\n`; ferramentas de rede, proxy web, stream, snapshot, Telegram relay alcancando loopback, Docker, metadata ou rede de outro cliente; scripts `.rsc` gerados |
| 4 | Superficie publica | Toda rota sem login (`security.py`), webhooks (assinatura Meta), health, nginx (`deploy/nginx`), portas no compose, Zabbix/Grafana/go2rtc expostos, CORS, CSP/HSTS, limites de upload e de taxa |
| 5 | Segredos e infraestrutura | Codigo, docs, testes e HISTORICO do git (`git log -p -S`); ENV da imagem (`deploy/imagem`), containers root, `network_mode: host`, iso-provisioner, scripts de host, backup sem criptografia, chave junto do dado, dependencias sem trava |
| 6 | XSS e apps | `frontend/js`: `innerHTML` com dado nao escapado, `esc()` e aspas simples, `onclick` montado, proxy web do equipamento na mesma origem, onde fica o token; `mobile/*`: backup, armazenamento do token, WebView. Prioridade: dado que vem de quem nao tem conta (nome de camera, WhatsApp, PDV, agente Windows) |
| 7 | Ataque pratico local | Copiar o repo para `/tmp/sightops-pentest`, subir com `DATABASE_BACKEND=sqlite` e `AUTH_REQUIRED=1` em 127.0.0.1, criar admin + 2 clientes + 1 visualizador e atacar: GETs sem token, IDOR entre clientes, visualizador escrevendo, forca bruta com XFF, logout/troca de senha, injecao (canario em /tmp), upload, `/api/backup/export`, cabecalhos. So localhost. Separar "confirmado" de "suspeita". Matar os processos no fim |

## Consolidar

1. Juntar repetidos (achado em 2+ agentes conta mais).
2. Conferir pessoalmente no codigo os 2 ou 3 mais graves antes de afirmar;
   descartar falso alarme (ex.: chave PUBLICA de WireGuard nao e segredo).
3. Entregar: nota geral, depois "Criticos: fechar esta semana", "Altos: 2-3
   semanas", "O que passou", e o que conferir em producao (so leitura, pelo
   usuario ou com acesso combinado).
4. Nao corrigir nada sem o usuario pedir. Correcao vai em ramo, um commit por
   assunto, publicacao pelo `/sightops-publicar`. Ligar o modo "valer" de
   permissoes muda o dia a dia dos usuarios: so com o dono.

Resultado da primeira rodada (05/11/2026): `docs/analise-2026-11-05.md`.
