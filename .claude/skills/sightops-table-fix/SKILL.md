---
name: sightops-table-fix
description: Corrige tabelas densas do frontend do SightOps (cam-snapshot-web-v2/frontend) que tem scroll horizontal indesejado ou colunas cortadas — Cameras IP, Gravadores (NVR/DVR), OLT, modais de edicao em lote. Baseado em uma correcao real aplicada e validada em producao (10.10.12.7).
---

# SightOps Table Fix Skill

Use esta skill quando o usuario reportar que uma tabela do SightOps (`C:\PROJETOS\cam-snapshot-web-v2\frontend`) tem scroll horizontal indesejado, colunas cortadas, ou pedir para aplicar a mesma correcao de tabela em outra tela.

## Contexto (licao aprendida nesta sessao)

A primeira tentativa de corrigir a tabela "Cameras IP" usou **larguras fixas em px** calculadas a mao (ex: `IP: 132px, MAC: 150px`) tentando somar menos que a largura da tela do usuario. Isso **falhou em producao**: o calculo de "largura disponivel" a partir de resolucao de monitor nao bate com a largura real em CSS px, porque zoom do navegador e escala de tela do Windows (125%/150%) reduzem o espaco disponivel sem que isso seja visivel na captura de tela. Qualquer largura fixa em px pode, portanto, sempre ultrapassar o container em algum zoom/monitor.

**A unica solucao que garante matematicamente zero scroll horizontal, independente de zoom/resolucao, e usar larguras em % que somam exatamente 100%, e nunca forcar um `min-width` em px maior que o container.** Percentual sempre resolve relativo ao container disponivel — nao ha como estourar.

## Diagnostico obrigatorio

Para cada tabela candidata, verifique estes 3 pontos (nesta ordem, os 3 juntos sao o padrao do bug):

1. A tabela tem `table-layout:fixed` e um `colgroup` com larguras?
2. As larguras do colgroup estao em **px** (ou uma mistura com poucas em %)?
3. Existe um `min-width:XXXpx` fixo no `<table>` (inline no HTML) **ou** codigo JS que faz `table.style.minWidth = soma_dos_px + 'px'` ao renderizar as linhas?

Se sim aos 3 (ou a qualquer combinacao que resulte numa largura total maior que o container em telas normais), a tabela vai ter scroll horizontal. Tabelas com `table-layout:auto` e sem `min-width` forcado (a maioria das telas simples de 5-7 colunas do sistema) normalmente NAO tem esse problema — nao mexa nelas a menos que o usuario reporte scroll especificamente ali.

### Como encontrar todas as tabelas afetadas no projeto

```bash
grep -n 'table-layout:fixed' frontend/index.html
grep -n 'min-width:[0-9]*px' frontend/index.html
grep -n "cols:\s*\[" frontend/app.js          # arrays de largura por view (px ou %)
grep -n 'style.minWidth' frontend/app.js       # JS que forca minWidth
```

Tabelas ja identificadas com este padrao no repo (podem ter sido corrigidas ja, confira antes):

| Tabela | Tela | HTML | Definicao de colunas (JS) |
|---|---|---|---|
| Cameras IP (basico/OLT/switch) | Inventario > Cameras IP | `#invOltTableEl` (~linha 327) | `INV_COLS` em `app.js`, renderizado por `renderInvOlt()` |
| Gravadores NVR/DVR (basico/olt/switch) | Inventario > Gravadores | tabela ~linha 536 | `NVR_COLS` / `DVR_COLS` em `app.js`, renderizado por `renderNvrTable()` |
| OLT (PON/ONU/serial/MAC/VLAN) | OLT | `#oltTableBody` (~linha 1353) | estatica, sem JS forcando minWidth |
| Editar cameras (modal em lote) | modal `#modalEditCam` | `#editCamTable` (~linha 1871) | estatica |
| Editar canais gravadores (modal em lote) | modal `#modalEditRec` | `#editRecTable` (~linha 1936) | estatica |

## Padrao de correcao

1. **Identifique as colunas identificadoras** (nunca podem ficar ilegiveis): IP, MAC, PON, ONU ID, ONU Serial, Switch IP, Porta, VLAN, Host. Deem a elas a maior fatia percentual disponivel.
2. **Identifique as colunas descritivas** (podem truncar com reticencias + tooltip): Titulo, Modelo, Fabricante, Local, ONU Name. O CSS base (`.data-table td { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }`) ja faz isso funcionar — so precisa que a celula tenha um `title="valor completo"` (o codigo do projeto ja faz isso em quase todas as celulas via `_camCell`/`row:`).
3. **Converta o array de larguras (`cols:`) de px para %, somando exatamente 100.** Se uma view tiver poucas colunas (ex: Basico com 9), a coluna Titulo pode ficar generosa (16-18%); views com muitas colunas (OLT com 13) precisam de fatias menores por coluna.
4. **Remova qualquer `min-width` fixo em px**, tanto inline no HTML (`style="...;min-width:1280px"` -> so `table-layout:fixed;width:100%`) quanto no JS (`table.style.minWidth = ...`). Se o JS calculava minWidth somando os px do array `cols`, substitua por `table.style.minWidth = ''` (ou remova a linha) — colunas em % dispensam min-width, pois `width:100%` + `table-layout:fixed` ja garantem que a tabela nunca excede o container.
5. **Atualize o colgroup estatico no HTML** para bater com os valores em % (evita flash de layout errado antes do JS rodar, quando aplicavel).
6. Se a tabela tiver varias "views" (como Basico/OLT/Switch), ajuste as % de cada view separadamente — views com mais colunas tecnicas (OLT/Switch) tem menos % sobrando para as colunas descritivas.

## Ajuste fino apos deploy (frequente)

Depois do primeiro deploy, e comum o usuario reportar que uma coluna especifica cortou demais (normalmente Titulo, por ser a mais lida). Correcao: tire 1-2% das colunas com folga obvia (ImgBB "up/down", Status "online/offline" quando nao ha valores longos tipo `auth_failed`, PON/ONU ID numericos curtos) e adicione a coluna reclamada. Sempre confira que a soma continua exatamente 100 antes de reimplantar.

## Deploy em producao (10.10.12.7)

O frontend servido em `http://10.10.12.7/v2/` **nao e sincronizado automaticamente com o repo local** — e uma copia estatica dentro do container `sightops-nginx` (`/usr/share/nginx/html/v2/`). Toda mudanca em `frontend/*.js`/`frontend/*.html` so aparece em producao depois deste processo manual:

```bash
# 1. Backup do que esta rodando (SEMPRE antes de sobrescrever producao)
MSYS_NO_PATHCONV=1 "/c/Program Files/PuTTY/plink" -ssh -batch -pw <senha> central@10.10.12.7 \
  "BK=/home/central/backups/sightops_v2_\$(date +%Y%m%d_%H%M%S) && mkdir -p \$BK && \
   docker cp sightops-nginx:/usr/share/nginx/html/v2/app.js \$BK/app.js && \
   docker cp sightops-nginx:/usr/share/nginx/html/v2/index.html \$BK/index.html && echo BACKUP_OK:\$BK"

# 2. Upload dos arquivos atualizados
MSYS_NO_PATHCONV=1 "/c/Program Files/PuTTY/pscp" -pw <senha> "C:\PROJETOS\cam-snapshot-web-v2\frontend\app.js" central@10.10.12.7:/tmp/app.js.new
MSYS_NO_PATHCONV=1 "/c/Program Files/PuTTY/pscp" -pw <senha> "C:\PROJETOS\cam-snapshot-web-v2\frontend\index.html" central@10.10.12.7:/tmp/index.html.new

# 3. Aplica dentro do container e recarrega nginx
MSYS_NO_PATHCONV=1 "/c/Program Files/PuTTY/plink" -ssh -batch -pw <senha> central@10.10.12.7 \
  "docker cp /tmp/app.js.new sightops-nginx:/usr/share/nginx/html/v2/app.js && \
   docker cp /tmp/index.html.new sightops-nginx:/usr/share/nginx/html/v2/index.html && \
   docker exec sightops-nginx nginx -t && docker exec sightops-nginx nginx -s reload && echo DEPLOY_OK"
```

Notas importantes:
- No Git Bash do Windows, sempre prefixe os comandos `plink`/`pscp` com `MSYS_NO_PATHCONV=1` — sem isso, caminhos Unix (`/home/...`, `/tmp/...`) dentro da string do comando remoto sao "corrigidos" incorretamente pelo MSYS e a linha de comando fica corrompida.
- Sempre faca backup antes de sobrescrever (passo 1) — e producao real de cliente.
- Depois do deploy, confirme que o arquivo certo subiu antes de avisar o usuario: `docker exec sightops-nginx grep -c "<algum trecho unico do que voce mudou>" /usr/share/nginx/html/v2/app.js` deve retornar `1`.
- Nunca afirme "deve ter funcionado" sem essa confirmacao — e nunca afirme que testou visualmente: nao ha ferramenta de browser/screenshot neste ambiente. Peca ao usuario para dar Ctrl+Shift+R e confirmar.
- Credenciais do servidor central (10.10.12.7) estao na memoria do projeto (`server_central_credentials.md`).
