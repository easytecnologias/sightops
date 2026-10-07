---
name: sightops-resolver
description: Aplica as correcoes SEGURAS do plano da ultima auditoria do SightOps (cam-snapshot-web-v2) sem precisar de nova explicacao. Modo conservador — conserta sozinho apenas o que e de baixo risco (codigo, docs, frontend, higiene do repo) e PARA para perguntar antes de qualquer coisa que toque OLT/equipamento vivo, banco de producao, deploy ou git push. Use quando o usuario disser "resolve", "corrige", "aplica as correcoes", "arruma isso" ou equivalente, referindo-se aos achados de uma auditoria SightOps.
---

# SightOps Resolver Skill

Use esta skill quando o usuario disser **"resolve"**, **"corrige"**, **"arruma"**, **"aplica as correcoes"** ou equivalente, se referindo aos problemas encontrados numa auditoria do SightOps (`C:\PROJETOS\cam-snapshot-web-v2`). E o par de execucao da skill `sightops-audit`: a auditoria acha e classifica; esta skill conserta o que e seguro.

> Se nao existe auditoria previa e o usuario esta relatando um sintoma que ele
> ve agora em producao, a skill certa e `sightops-bug-producao` (sintoma ->
> causa -> correcao publicada e provada). Esta aqui executa um plano ja feito.

O usuario ja definiu o comportamento uma vez e nao quer reexplicar. As regras abaixo SAO a decisao dele — siga sem pedir confirmacao para o que e verde, sempre pergunte para o que e amarelo/vermelho.

## Regra de trafego (a decisao ja tomada pelo usuario)

Modo **conservador**. Toda correcao cai em uma de tres faixas:

### 🟢 VERDE — pode aplicar sozinho, sem perguntar
Baixo risco, reversivel, nao sai da maquina de desenvolvimento:
- Editar codigo-fonte (backend Python, frontend JS/CSS/HTML).
- Corrigir bug local, tabela torta, validacao faltando, tratamento de erro.
- Atualizar documentacao (`README.md`, `CHANGELOG.md`, `docs/*.md`).
- Remover/arquivar codigo morto (ex.: `frontend/app.js` orfao).
- Higiene do repositorio: mover chave/segredo solto para fora do repo, apagar tarball versionado por engano, ajustar `.gitignore`.
- Adicionar/ajustar log, mensagem de erro, comentario.
- Rodar verificacao segura: `python -m compileall app`, `python -B -c "import app.main"`, grep, leitura de arquivo.

### 🟡 AMARELO — PARE e pergunte antes
Muda estado versionado ou compartilhado, mas nao toca producao/equipamento:
- `git commit` (mesmo local). Proponha a divisao em commits logicos e espere o ok.
- Instalar/atualizar dependencia (`requirements.txt` + `pip install`).
- Mudar schema de banco / criar migration.
- Apagar arquivo que voce nao criou, ou grande volume de arquivos.
- Alterar `.env`, `docker-compose*.yml`, config de auth/`security.py`.

### 🔴 VERMELHO — NUNCA sozinho, sempre confirmacao explicita
Irreversivel ou toca cliente/producao:
- Qualquer comando que chegue numa **OLT, DVR, NVR, RouterOS ou camera real** (drivers em `app/cli/tools/olt_*`, `olt_fiberhome.py`, conectores). Equipamento vivo de cliente.
- Banco de **producao**, rodar migration em producao.
- **Deploy** / mexer nos containers de producao (`sightops-nginx`, `sightops-tls`) / servidor 10.10.12.7.
- `git push`, publicar imagem, qualquer coisa que saia para `origin` ou para fora.
- Rodar migration destrutiva, `git reset --hard`, apagar `data/`/`output/`.

Na duvida entre faixas, trate como a faixa MAIS restritiva.

## Processo

### 1. Descobrir o que resolver (o plano vem da ultima auditoria)

O escopo e **o plano de correcao da ultima auditoria SightOps**, executando so os itens 🟢.

1. Se ha uma auditoria recente no contexto da conversa (a skill `sightops-audit` acabou de rodar), use o "Plano de correcao" dela — especificamente os itens listados como "imediatos / baixo risco".
2. Se NAO ha auditoria no contexto (sessao nova, contexto perdido), **nao adivinhe**: rode uma redescoberta rapida e somente-leitura para reconstruir a lista de itens verdes atuais:
   ```bash
   git -C "C:\PROJETOS\cam-snapshot-web-v2" status
   git -C "C:\PROJETOS\cam-snapshot-web-v2" diff --stat
   python -m compileall app   # confirma que o repo esta saudavel antes de mexer
   ```
   Depois cheque os pontos verdes recorrentes do SightOps (ver secao abaixo). Se mesmo assim nao der para reconstruir com seguranca o que a auditoria pediu, pergunte ao usuario qual auditoria/lista ele quer aplicar — nao invente correcoes.

### 2. Separar por faixa e agir
- Liste rapidamente o que caiu em 🟢, 🟡 e 🔴.
- Aplique **todos os 🟢** direto, um a um.
- Para 🟡 e 🔴: **nao aplique**. Liste como "precisa da sua confirmacao" com uma frase de por que.

### 3. Validar depois de mexer
Sempre que editar backend Python:
```bash
python -m compileall app && python -B -c "import app.main; print('app.main OK')"
```
Se editar frontend JS, cheque sintaxe do arquivo tocado (`node -e "new Function(require('fs').readFileSync('frontend/js/ARQUIVO.js','utf8'))"`).
Se algo quebrar, reverta a mudanca que quebrou e reporte — nao empilhe correcao em cima de repo quebrado.

### 4. Entregar o relatorio
Formato de saida obrigatorio:

```
# Resolvido (modo conservador)

## Feito sozinho (🟢)
- <arquivo>: <o que mudou> — <validacao: compila/importa ok>
...

## Precisa da sua confirmacao (🟡/🔴)
- 🟡 <item> — por que parei: <motivo>
- 🔴 <item> — por que parei: <motivo>

## Validacao
- compileall: ok/erro
- import app.main: ok/erro

## Proximo passo
<uma linha: o que voce quer que eu faca com os itens amarelos/vermelhos>
```

## Pontos verdes recorrentes do SightOps (checklist de redescoberta)

Quando precisar reconstruir a lista sem uma auditoria fresca, estes sao os itens 🟢 classicos deste repo — confirme se ainda procedem antes de aplicar:
- `CHANGELOG.md` desatualizado vs. `APP_VERSION` em `app/core/settings.py`.
- `frontend/app.js` (monolito legado ~486 KB) — orfao se `frontend/index.html` so carrega `js/*.js`. Confirme que nao esta referenciado antes de remover/arquivar.
- Chave SSH / segredo solto na raiz (`_tmp_sightops_deploy_ed25519`, `*.tgz` de release) — gitignored mas fisicamente no repo. Mover para fora, nunca commitar.
- Tabelas do frontend com scroll horizontal / colunas cortadas → existe a skill dedicada `sightops-table-fix`; invoque-a em vez de improvisar.
- Falta de `to_thread` em operacao pesada sincrona dentro de rota `async`.
- Tratamento de erro / log faltando em fluxo de conector.

## Limites rigidos (nunca cruze, mesmo com "resolve tudo")
- Nao mande comando para OLT/DVR/NVR/RouterOS/camera real. Isso e 🔴 sempre.
- Nao faca `git commit`, `git push`, deploy, nem toque em producao sem "sim" explicito para AQUELE passo.
- Nao exponha valor real de `.env`, token, senha ou chave privada. Se encontrar segredo, diga o arquivo e o tipo, mascare o valor.
- Um "sim" para um passo nao vale para o proximo. Cada acao amarela/vermelha precisa do seu proprio ok.
- Se o usuario disser "resolve tudo incluindo commitar/deploy", isso muda a faixa daquele pedido especifico — mas confirme em uma frase o que vai fazer antes de fazer, porque contradiz o padrao conservador que ele definiu.
