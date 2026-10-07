# SightOps v3 — instruções para agentes

Plataforma SaaS de operação de CFTV/ISP (câmeras, gravadores, OLT/ONU, switches,
controle de acesso, alerta de pânico). Vários clientes (tenants) numa instalação.
Responda ao usuário **sempre em português**.

## Onde está cada coisa (o que mais engana)

**Produção não vem do git.** São quatro lugares que divergem sem avisar:

| O quê | Onde mora | Sobrevive a recreate? |
|---|---|---|
| Backend | imagem Docker local `sightops-prod-api:<data>-<assunto>`, container `sightops-v3-api` | só se virou imagem (`docker commit`) |
| Tag no ar | `CAM_SNAPSHOT_IMAGE` em `/home/central/sightops-v3-release/.env.v3` (não versionado) | sim |
| Frontend | bind mount `/home/central/sightops-v3-release/frontend` | sim, mas **não está no git** até copiar |
| Git | `/home/central/sightops-v3` → `easytecnologias/sightops` (branch `main`) | — |

- Este repositório é o **do servidor**. Uma cópia em outra máquina é só leitura.
- O repo `cam-snapshot-web-v2` é o v2/homologação: **não** é este.
- Push é feito pelo usuário. Commit sim; push não.

## Publicar (ver skill `/sightops-publicar`)

Corrija sempre **sobre o arquivo que está rodando** (`docker cp sightops-v3-api:/app/<arq> /tmp/`)
e aplique só o seu diff. Copiar do git por cima já apagou trabalho de outro agente
em produção. O `docs/DEPLOY.md` descreve `docker build`; a prática atual é
`docker cp` → `docker restart` → `docker commit` → trocar a tag no `.env.v3`.

- `docker cp` sem `commit` **some** no próximo recreate.
- Frontend: subir o `?v=` do arquivo no `index.html`, **com número inédito**
  (maior que todos os já usados). Reusar número serve JS velho pelo Cloudflare.
- A lista de `<script>` do `index.html` não pode mudar sem o arquivo existir no servidor.
- Imagem perto de ~110 camadas: achatar com `deploy/imagem/achatar-imagem.sh`.
- Depois de publicar: logs sem traceback e o md5 do container igual ao arquivo novo.

## Regras do domínio que já custaram caro

- **Tudo no Zabbix.** É a premissa vendida aos clientes: todo equipamento
  (câmera, gravador, OLT, ONU, switch, conector) tem host no Zabbix com dados.
  Recurso novo de monitoramento só está pronto quando chega lá
  (`app/services/zabbix_monitoring_service.py`).
- **Isolamento entre clientes.** Todo dado gravado passa por
  `tenant_scoped_path` / `get_current_tenant_slug()`; cache em memória precisa de
  chave de tenant. Equipamento atrás de conector isolado só responde pelo **IP
  virtual (vnat)**: `connector_routing_vnat`. IP real dá `No route to host` e engana.
- **Rota de escrita nova** (POST/PUT/DELETE) toma 403 até ser declarada em
  `_role_rules` (`app/core/security.py`).
- **Equipamento de cliente é vivo.** Nada de comando de escrita em OLT, DVR/NVR,
  MikroTik ou câmera sem o usuário pedir. Na FiberHome, ajuda (`?`) nunca leva Enter:
  use `FiberHomeTelnet.ajuda()`.
- **Nunca testar `save_person` com pessoa real**: sem `id`, resolve por CPF/matrícula
  e faz UPDATE completo.
- Falha silenciosa é o padrão dos bugs daqui: campo que não existe, tipo diferente
  do esperado (`"nao"` é string verdadeira), `except` mudo.

## Verificar antes de dizer pronto

```bash
python -m compileall -q app && python -c "import app.main"
python -m pytest tests -q          # testes com fixtures reais de equipamento
node --check frontend/js/<arquivo>.js
```

Prova é número de produção antes/depois, não "deve funcionar".

## Skills do projeto (`.claude/skills/`)

`sightops-publicar` (deploy), `sightops-conferir-servidor` (antes de push/reboot),
`sightops-bug-producao` (sintoma em produção), `sightops-auditar-estado`
(tela mostra estado errado), `sightops-audit` / `sightops-resolver` (varredura e
correções seguras), `sightops-integracoes` (acoplamento entre serviços).
Algumas citam caminhos do v2; neste repo vale a tabela acima.
