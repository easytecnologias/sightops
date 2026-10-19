---
name: sightops-sincronizar
description: Deixa iguais producao (container + frontend publicado), o git do servidor, o GitHub e a copia desta maquina, sem perder trabalho de nenhum lado. Use quando o usuario pedir para "deixar tudo igual", "sincronizar", "alinhar servidor, computador e github", ou depois que o sightops-conferir-servidor acusar divergencia.
disable-model-invocation: true
---

# Sincronizar o SightOps v3

O `sightops-conferir-servidor` diz **o que** diverge. Esta skill **resolve**, na
ordem em que nada se perde. Foi feita a partir de 14/10/2026, quando havia:
codigo so na imagem (download de trecho do gravador), tela so no release
(Investigacao), trabalho sem commit no servidor (Manutencao), e uma copia do
Windows 54 commits atras com um servico inedito escondido no meio de versoes
velhas.

Acesso: `ssh sightops '...'` e `scp arq sightops:/tmp/` (chave, alias em
`~/.ssh/config`). **Nunca** `plink -pw`: o hook nega, e a senha ficaria na
transcricao.

## Ordem (nao pule)

### 1. Fotografar

```bash
scp .claude/skills/sightops-conferir-servidor/conferir.sh sightops:/tmp/
ssh sightops 'cd /home/central/sightops-v3 && bash /tmp/conferir.sh'
```

Anote os blocos 1, 3, 4 e 5. Se o bloco 3 acusar arquivo, confira se nao e so
CRLF (`tr -d '\r'` dos dois lados): docker cp feito do Windows leva CRLF e o
codigo e o mesmo.

### 2. Producao -> git do servidor (o que so existe no ar)

Para cada DIFERE **real** do bloco 3, decida o lado certo:

```bash
# o container e mais novo que o git? (git log do arquivo x data no container)
ssh sightops 'cd /home/central/sightops-v3; git log -1 --format=%ci -- ARQ; \
  docker exec sightops-v3-api stat -c %y /app/ARQ'
```

- **Container mais novo** (publicado sem commit): `docker cp sightops-v3-api:/app/ARQ ARQ`.
- **Git mais novo, container == versao anterior do git** (commitado e nao
  publicado): o git esta certo; isso se resolve publicando
  (`/sightops-publicar`), nao aqui.
- **Os dois mudaram**: pare e mostre o diff ao usuario.

Frontend (bloco 4): `cp /home/central/sightops-v3-release/frontend/ARQ frontend/ARQ`.
`bak-*` dentro do release nao e codigo: mova para `/home/central/backups-frontend/`.

Arquivo sem commit no working tree do servidor: pergunte de quem e (o Codex
trabalha em paralelo). Sendo do usuario, entra no commit.

### 3. Provar antes de commitar

Com a imagem que esta no ar, sem tocar no container de producao:

```bash
ssh sightops 'cd /home/central/sightops-v3; IMG=$(docker inspect sightops-v3-api --format "{{.Config.Image}}"); \
  docker run --rm -e PYTHONPYCACHEPREFIX=/tmp/pyc -v $PWD/app:/src/app:ro -v $PWD/tests:/src/tests:ro \
  -v $PWD/deploy:/src/deploy:ro -v $PWD/scripts:/src/scripts:ro \
  -w /src --entrypoint sh $IMG -c "pip install -q pytest >/dev/null 2>&1; python -c \"import app.main\" && python -m pytest tests -q -p no:cacheprovider | tail -3"'
```

`-v $PWD:/src` inteiro nao serve: o app cria `data/` no import e o mount e
somente leitura. Monte `app/` e `tests/`, mais `deploy/` e `scripts/` (o teste
de isolamento do Ruijie carrega o iso-provisioner e o sync do tunel de la).

Depois de `/sightops-publicar`, a imagem que vale e a do `.env.v3` (o container
pode ainda estar na anterior ate ser recriado): use
`IMG=$(grep ^CAM_SNAPSHOT_IMAGE= /home/central/sightops-v3-release/.env.v3 | cut -d= -f2)`.

### 4. Commitar no servidor

Um commit por assunto, mensagem dizendo **de onde veio** ("rodava na imagem X
e nao estava no git"). Identidade: `SightOps <suporte@easytecnologias.com.br>`.
Mensagem longa: escreva um script local e mande por `scp`.

### 5. Esta maquina -> servidor

```bash
git fetch servidor
git rev-list --left-right --count servidor/main...HEAD    # atras / a frente
git status --porcelain
```

Com arquivos sem commit e a copia atrasada, **nao** descarte nada antes de
saber o que e inedito. Para cada arquivo:

- versionado: merge de tres vias
  `git merge-file -p local base(=HEAD local) servidor`; resultado igual ao do
  servidor = "ja esta la".
- nao versionado: `git hash-object` do conteudo (sem `\r`) e, no servidor,
  `git cat-file -e <hash>`; existe = e versao antiga de algo que o servidor ja tem.

Depois:

1. Tudo num ramo de seguranca: `git switch -c backup/windows-AAAAMMDD && git add -A && git commit`.
2. `git switch main && git merge --ff-only servidor/main`.
3. O que era **inedito** vai para um ramo `wip/<assunto>` em cima do main,
   enviado com `git push servidor wip/<assunto>`. So entra no main depois de
   pronto (ligado, testado, com numero de producao).

Mudanca local para o main do servidor: o repo de la nao e bare e o `main` esta
em uso, entao `git push servidor main` e recusado. Use
`git push servidor main:sync-windows` e, no servidor,
`git merge --ff-only sync-windows && git branch -d sync-windows`.

### 6. GitHub

O push e do usuario: `cd /home/central/sightops-v3 && git push origin main <ramos wip>`.
Depois confira: `git fetch origin && git rev-parse main origin/main`.

### 7. Fechar

Rode o `conferir.sh` de novo. O alvo e a ultima linha
`TUDO CERTO: pode dar push e reiniciar sem perder nada`. Se sobrou so
"no ar != .env.v3" e "codigo solto" logo depois de um `/sightops-publicar`,
falta recriar o container a partir da imagem nova (`compose up -d --no-deps
cam-snapshot-api`, com `--dry-run` antes) -- isso e do usuario.

## Como reportar

Uma tabela com os quatro lugares (GitHub, git do servidor, esta maquina,
producao) e o commit de cada. Em linguagem de operacao: "o download de trecho
so existia na imagem" e nao "recorder_driver.py diverge".
