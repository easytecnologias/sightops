---
name: sightops-bug-producao
description: Caca e conserta bug do SightOps que o usuario esta SENTINDO agora em producao (10.10.12.7) — "apaguei e voltou", "o filtro nao funciona", "nao consigo apagar o site", "ta lento", "as fotos nao vem", "isso nunca funcionou", "ta muito bugado". Vai do sintoma ate a correcao publicada e provada com numero. Use SEMPRE que o usuario relatar comportamento errado no sistema em uso, mesmo que ele nao diga a palavra "bug" — inclusive quando ele estiver irritado, disser que "piorou", que teve que fazer algo na mao, ou mandar "resolve isso". Diferente de sightops-audit (que varre o sistema procurando problemas) e de sightops-resolver (que aplica plano de auditoria ja feita): aqui existe UM sintoma concreto e o alvo e producao, nao o repo.
---

# Cacar bug em producao do SightOps

O usuario esta operando CFTV em campo. Quando ele relata um problema, ele ja perdeu tempo com aquilo — as vezes horas, as vezes fez o trabalho na mao. O valor aqui nao e "explicar o bug": e **devolver o sistema funcionando e provar que funciona**.

Esta skill existe porque o SightOps tem uma caracteristica que quebra o raciocinio normal de debugging: **producao nao e o repositorio**. Em 18/08/2026 producao rodava codigo de 06/08 — 65 commits atras — com patches manuais por cima. Corrigir olhando so o `main` produz uma correcao que nao aplica, ou pior, que derruba a API.

## O padrao que se repete nos bugs daqui

Quase todo bug que apareceu neste sistema **falha em silencio**. A tela nao mostra erro; simplesmente nao faz o que deveria. Exemplos reais, todos confirmados:

- Apagar camera "funcionava" e a camera voltava (a varredura desfazia o bloqueio).
- Apagar site nao apagava nada (a tela filtra por `local`, o backend comparava `site`).
- Deslocar IPs falhava em 100% dos casos (frontend nao mandava a mascara) e o log escrevia `undefined` no sucesso E no erro.
- Filtro da tela OLT morria no meio (campo `vlan` vem numero, codigo fazia `.toLowerCase()`).
- Zabbix acumulou 1462 hosts fantasma (o sync so tinha create/update, nunca delete).

Por isso: **suspeite primeiro de campo que nao existe, tipo diferente do esperado, e excecao engolida**. Um `res.msg` que o backend nunca devolve, um `String()` faltando, um `if not achou: return` calado. Se a tela "nao faz nada", raramente e a rede — normalmente e uma excecao morrendo dentro de um `.some()` ou de um `try/except` mudo.

## Fluxo

### 1. Meca o sintoma em producao antes de abrir o codigo

Nao comece pelo `grep`. Comece pelo dado, porque ele delimita o problema e vira a prova do "depois".

```bash
# estado real (o inventario vive no volume, por tenant)
docker run --rm -v sightops-prod-release_sightops_prod_data:/d python:3.11-alpine python -c "..."
# latencia por endpoint, direto do host (docker exec adiciona overhead e engana)
curl -s -o /dev/null -w '%{time_total}\n' http://127.0.0.1/api/...
```

Cruze o que o usuario ve com o que esta gravado. Foi assim que 1462 hosts fantasma viraram numero em vez de impressao, e que "apaguei e voltou" virou "16 linhas com `source: olt-sync` reapareceram".

Quando o sintoma for de tela ("nao filtra", "botao nao faz nada"), o console do navegador e a fonte da verdade — Playwright ja esta instalado nesta maquina:

```python
pg.on("pageerror", lambda e: erros.append(str(e)))
pg.goto("https://sightops.easytecnologias.com.br/v2/")
```

Da para injetar dados reais e disparar o evento do jeito que o usuario dispara, sem precisar de login. Foi o que revelou `(f || "").toLowerCase is not a function`.

### 2. Confirme a causa no codigo, com file:line

Uma hipotese so vale depois de bater com o codigo. Leia o caminho inteiro: rota -> service -> o que grava. E pergunte-se **quem mais mexe naquele dado** — no SightOps tres caminhos criam camera sozinhos:

- `scan_service.run_http_scan` (varredura HTTP)
- `ws_scan_service` (varredura via conector)
- `olt_service` (sync automatico da OLT, roda em background)

Corrigir um so deixa o bug vivo pelos outros dois. O "apaguei e voltou" era exatamente isso.

### 3. Corrija sobre a base de PRODUCAO, nunca sobre o main

Este e o passo que mais da errado. Extraia o arquivo que esta rodando e aplique **apenas o seu diff** nele:

```bash
docker cp sightops-prod-api:/app/app/services/X.py /tmp/X.py
```

Copiar o arquivo do `main` por cima parece atalho e nao e: em 18/08 o `ws_scan_service.py` do repo importava `connector_target_scope`, que nao existe na versao de producao — a API nao subia. No frontend o erro e pior e mais sutil: o `index.html` do repo carrega `accessControl.js`, que nao existe no servidor; o 404 quebra o JS inteiro e **nem o botao Entrar funciona**. Isso derrubou o login de producao.

Trave isso no seu script de patch:

```python
# a lista de <script> do index nao pode mudar
assert set(re.findall(r'src="js/([a-zA-Z]+\.js)\?', novo)) == set(...antigo...)
```

Cuidado com quebra de linha: os arquivos vem misturados (CRLF no repo, LF no servidor) e varios `.py` tem BOM. Normalize para casar os alvos e grave de volta no formato original, senao o `assert` falha sem motivo aparente.

### 4. Valide ANTES de trocar o container

Construa a imagem candidata e teste dentro dela. Este passo ja evitou derrubar producao mais de uma vez:

```bash
docker build -t sightops-prod-api:$(date +%Y%m%d)-<assunto> .
docker run --rm -e DATABASE_BACKEND=sqlite $TAG python -c 'import app.main'      # pega ImportError
docker run --rm -v ...data:/app/data:ro -e DATA_DIR=/app/data $TAG python /tmp/teste.py
```

Rode contra os **dados reais** (monte o volume como `:ro`). "468 de 469 linhas com foto encontrada, antes era 1" e uma prova; "acho que agora vai" nao e.

Quando a correcao apaga coisa, teste com a operacao destrutiva interceptada:

```python
def fake_api(metodo, params, auth=None):
    if metodo == "host.delete":
        removidos.extend(params); return {"hostids": params}
    return _orig(metodo, params, auth)
```

Assim voce ve exatamente o que seria removido sem remover nada.

### 5. Publique e prove

O deploy de producao esta em `[[sightops-deploy-producao-real]]` — leia antes, ele tem as armadilhas (imagem local por tag, `.env.production`, container orfao, frontend por container por causa de permissao).

Depois de publicar, tres verificacoes que ja pegaram problema real:

1. **Erro nos logs**: `docker logs --since 5m sightops-prod-api | grep -iE 'traceback|exception'`
2. **Meca de novo** o mesmo numero do passo 1 e mostre antes/depois.
3. **Confira o nginx** se recriou container. Ele resolvia o nome da API so no start e ficava preso no IP velho — 3s de timeout por requisicao, sentido pelo usuario como "ta lento". Ja corrigido com resolver dinamico, mas confirme: `curl` algumas vezes e veja se aparece pico de ~3s.

No frontend, suba o `?v=` do script alterado no `index.html`. Sem isso o navegador serve o arquivo antigo e voce (e o usuario) conclui que a correcao nao funcionou.

## O que exige o usuario

Pare e peca, explicando o porque em uma linha:

- **Abrir porta / regra de firewall** (expoe servico na internet).
- **Exclusao em massa** (centenas de registros, mesmo com backup).
- **Mexer em OLT/equipamento vivo** alem de leitura.
- **git push** — producao nao sai do git aqui, entao commit nunca e o caminho para corrigir producao.

Quando for algo que voce nao pode executar, entregue o comando pronto para ele colar. Melhor ainda: veja se a propria correcao resolve o passivo sozinha — a poda do Zabbix limpa os 1462 fantasmas no proximo sync completo, sem ninguem rodar script de limpeza.

## Antes de mexer

Backup do que voce vai alterar, sempre em `/home/central/sightops-prod-backups/<timestamp>/`: arquivo original, `.env.production`, e o volume de dados quando o bug envolver inventario. Custa segundos e ja permitiu desfazer o frontend quebrado em um comando.

Atencao a um detalhe de Docker que engana: **bind mount segue o diretorio original**. Renomear a pasta do frontend e extrair o backup no lugar nao muda o que o nginx serve — ele continua no inode antigo. Restaure o conteudo *dentro* do mesmo diretorio.

## Como reportar

O usuario nao quer aula. Ele quer saber: era bug mesmo? ja funciona? o que eu faco agora?

Estrutura que funciona:

1. **O que estava acontecendo** — em linguagem de operacao, nao de codigo ("a tela filtra por um campo e o backend comparava outro"), com o `file:line`.
2. **A prova** — numero de antes e de depois.
3. **O que falta para ele** — recarregar com Ctrl+Shift+R, rodar o sync, aprovar algo.

Se voce errou no meio do caminho, diga em uma frase e siga. Aconteceu de eu concluir "funcionou" olhando IPs que respondiam, quando na verdade o usuario tinha feito na mao — ele corrigiu com "EU QUE FIZ MANUAL". Verifique se o *sistema* fez, nao se o estado final esta certo.

E quando ele estiver irritado dizendo que o programa piorou: ele geralmente tem razao sobre o sintoma, mesmo quando a causa que ele imagina esta errada ("sera que ta bloqueado na OLT?" — nao estava, a VLAN era a mesma). Investigue a hipotese dele de verdade e responda com evidencia, sem defender o sistema.

## Acesso

Servidor `10.10.12.7` (usuario `central`). Se a rede local cair no meio do trabalho — acontece — troque para o IP publico sem avisar e siga: ver `[[sightops-acesso-alternativo-ip-publico]]`. A faixa `100.65.x` (cameras, DVR/NVR) costuma continuar acessivel mesmo quando a `10.10.x` cai.

Relacionado: `[[sightops-deploy-producao-real]]`, `[[sightops-deploy-model]]`, skill `sightops-audit` (varredura ampla), skill `sightops-resolver` (aplicar plano de auditoria).
