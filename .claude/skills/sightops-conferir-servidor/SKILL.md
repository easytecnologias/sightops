---
name: sightops-conferir-servidor
description: Confere se maquina, servidor (10.10.12.7) e GitHub estao sincronizados e se um reboot ou recreate de container nao vai apagar trabalho. Use ANTES de dar push, ANTES de reiniciar o servidor ou recriar container, DEPOIS de publicar imagem nova, e sempre que o usuario pedir "ve se ta tudo certo", "verifica se bate", "pode dar push?", "se eu reiniciar perde algo?" ou reclamar que "mudou tudo" / "sumiu o que a gente fez". Diferente de sightops-audit (que procura bug no codigo): aqui a pergunta e se o que ja existe esta gravado nos lugares certos.
---

# Conferir servidor, repositorio e sobrevivencia a reboot

O SightOps tem uma caracteristica que quebra a intuicao: **producao nao vem do
git**. O que roda vem da IMAGEM Docker, o frontend vem de um bind mount em
disco, e a configuracao vem de um `.env.v3` que nao esta versionado. Sao quatro
lugares onde a mesma coisa pode estar diferente, e nenhum deles avisa quando
diverge.

O custo disso ja foi cobrado. Em 23/09/2026 o relatorio de gravadores saia em
PDF vetorial, com texto selecionavel. O modulo que fazia isso vivia so dentro
do container em execucao, aplicado a mao. No primeiro recreate ele sumiu e o
relatorio voltou a ser uma pilha de JPEGs. Ninguem notou por seis dias, e o
usuario descobriu sozinho: *"trabalhamos pro relatorio ficar assim, ai quando
fui olhar mudou tudo pq mexemos e nao salvamos"*.

Esta skill existe para essa pergunta nunca mais depender de alguem lembrar.

## Quando rodar

- **Antes de qualquer push** — e o pedido mais comum ("ve se bate pra gente
  fazer o push").
- **Antes de reiniciar o servidor ou recriar container.** Recreate e o momento
  em que codigo nao-persistido morre.
- **Depois de publicar imagem nova**, para confirmar que o que subiu e o que
  estava previsto.
- **Quando o usuario disser que algo "mudou sozinho" ou "sumiu"** — normalmente
  e isto, nao um bug novo.

## O que conferir

O script `conferir.sh` (neste diretorio) roda tudo de uma vez. Copie para o
servidor e execute:

```bash
pscp conferir.sh central@10.10.12.7:/tmp/     # ou cat > /tmp/conferir.sh
ssh central@10.10.12.7 'bash /tmp/conferir.sh'
```

Rodar a mao tambem serve; o que **nao** serve e pular blocos. Cada um dos doze
abaixo ja pegou um problema real.

### 1. Git do servidor

`/home/central/sightops-v3` e o repositorio de producao (`easytecnologias/sightops`).
O repo local da maquina e outro (homologacao) — nao confunda os dois.

```bash
cd /home/central/sightops-v3
git status --short          # tem que sair vazio
git fetch origin -q
git log --oneline origin/main..HEAD
```

Working tree sujo antes de um push significa que alguem (ou voce) deixou
trabalho pela metade. **O Codex trabalha em paralelo neste projeto**: nunca
commite arquivo alheio sem perguntar.

### 2. Imagem no ar x `.env.v3`

```bash
docker inspect sightops-v3-api --format '{{.Config.Image}}'
grep ^CAM_SNAPSHOT_IMAGE= /home/central/sightops-v3-release/.env.v3
```

Se divergirem, o container esta rodando uma versao e o proximo `up -d` (ou o
proximo boot) vai trocar por outra, sem aviso. Este e o item que transforma um
reboot inocente em "mudou tudo".

### 3. Backend: o que roda x o que esta no git

**Inclua `deploy/`.** O provisioner de isolamento mora lá e controla roteamento
e firewall dos túneis. Em 30/09/2026 ele rodava corrigido enquanto o git tinha a
versão anterior, e este bloco deu "0 divergentes" — porque olhava só `app/` e
`tools/`. Era exatamente o cenário que a skill existe para pegar, passando pelo
próprio verificador.

```bash
cd /home/central/sightops-v3
for f in $(git ls-files 'app/**/*.py' 'tools/*.py' 'deploy/**/*.py' 'deploy/**/*.sh'); do
  a=$(docker exec sightops-v3-api md5sum "/app/$f" 2>/dev/null | cut -d' ' -f1)
  b=$(md5sum "$f" | cut -d' ' -f1)
  [ "$a" != "$b" ] && echo "DIVERGE: $f"
done
```

Tres resultados possiveis, e os tres importam:

- **Difere** — alguem editou de um lado so.
- **So no git** — o commit existe mas nunca foi deployado.
- **So no container** — *este e o perigoso*. E codigo que morre no proximo
  recreate. Foi assim que o gerador ReportLab se perdeu.

### 4. Frontend: o que o `/v3/` serve x o git

O `/v3/` e proxy para outro nginx, que serve
`/home/central/sightops-v3-release/frontend` por bind mount. Isso **sobrevive a
reboot** (esta em disco), mas **nao esta no git** a menos que alguem copie.

```bash
cd /home/central/sightops-v3
R=/home/central/sightops-v3-release/frontend
for f in $(cd $R && find . -type f \( -name '*.js' -o -name '*.html' -o -name '*.css' \) | sed 's|^\./||'); do
  diff -q <(tr -d '\r' < "$R/$f") <(tr -d '\r' < "frontend/$f") >/dev/null 2>&1 || echo "DIVERGE: $f"
done
```

**Compare sempre normalizando `\r`.** Arquivos vem misturados (CRLF do Windows,
LF do servidor) e sem o `tr -d '\r'` tudo parece diferente. Ja perdi tempo
"corrigindo" um `config.js` que era identico byte a byte fora as quebras.

O risco aqui e silencioso ao contrario do backend: a correcao funciona hoje e
some no dia em que alguem publicar o frontend a partir do repo.

### 5. Codigo solto dentro do container

```bash
docker diff sightops-v3-api | grep -E '^[AC] /app/(app|tools)/' | grep -v __pycache__
```

Linhas de `__pycache__` e diretorios (`C /app/app/services`) sao normais. Um
arquivo `.py` aqui significa `docker cp` que ninguem transformou em imagem.

### 6. Montagens do disco — a armadilha do banco vazio

Os volumes dos dois Postgres moram em `/mnt/dados` e voltam por bind mount. **O
diretorio por baixo do bind esta vazio.** As montagens usam `nofail` de
proposito (um disco secundario com defeito nao pode prender a maquina no modo
de emergencia), mas isso significa que o boot segue mesmo se elas falharem — e
ai o Postgres acha `PGDATA` vazio e roda `initdb`. SightOps e Zabbix no ar com
banco novo em branco, parecendo perda total, gravando no lugar errado.

```bash
grep -cE "/mnt/dados" /etc/fstab                      # espera 3
mount | grep -cE "/mnt/dados|docker/volumes"          # espera 3
systemctl show docker.service -p RequiresMountsFor    # tem que listar as 3
```

O `RequiresMountsFor` vem do drop-in `10-espera-os-volumes.conf` (versionado em
`deploy/storage/systemd/`). Sem ele o Docker sobe sem esperar o disco.

### 7. Restart policy e existencia da imagem

```bash
docker inspect <container> --format '{{.HostConfig.RestartPolicy.Name}}'   # unless-stopped
docker image inspect $(grep ^CAM_SNAPSHOT_IMAGE= .../.env.v3 | cut -d= -f2)
```

As imagens sao **locais, por tag** — nao existe registry. Se a tag em uso sumir
(um `docker image prune -a` mal calibrado), o container nao volta.

### 8. Backup — e se a CHAVE esta dentro dele

Este item pegou um problema em 29/09/2026 que estava correndo ha dias:

```
2026-09-29 03:30:05 banco OK: v3-db-20260929-033001.sql.gz (3,0M)
tar: .env.v3: Funcao stat falhou: Arquivo ou diretorio inexistente
2026-09-29 03:30:05 ERRO: falhou o tar da configuracao
```

O dump do banco continuava saindo, entao de longe o backup parecia vivo. Mas
**sem a `SIGHTOPS_SECRET_KEY` o dump nao restaura nada de util**: as senhas das
OLTs ficam cifradas com uma chave que nao existe mais.

Nao basta ver que o backup rodou. Abra o tar:

```bash
tail -12 /mnt/dados/backups/sightops-db/backup.log     # procure "falhas: 0"
CFG=$(ls -1t /mnt/dados/backups/sightops-db/diario/v3-config-*.tar.gz | head -1)
tar tzf "$CFG"                                          # .env.v3 tem que estar
tar xzf "$CFG" -O .env.v3 | grep -c ^SIGHTOPS_SECRET_KEY=
```

E confira que a chave do backup e a mesma que esta no ar — backup com chave
velha e tao inutil quanto backup sem chave.

### 9. Camadas da imagem

Cada correcao publicada e um `FROM a anterior + COPY`, entao empilha uma camada.
O Docker para por volta de **130** e o build falha com `max depth exceeded` --
e falha na hora de PUBLICAR, o pior momento possivel. Aconteceu em 29/09/2026
com 131 camadas, no meio de uma correcao.

```bash
docker history -q $(grep ^CAM_SNAPSHOT_IMAGE= .../.env.v3 | cut -d= -f2) | wc -l
```

Passou de ~110, achate antes do proximo deploy:

```bash
bash deploy/imagem/achatar-imagem.sh <imagem-atual> <nova-achatada>
```

O `docker import` DESCARTA a configuracao (ENV, CMD, WORKDIR, EXPOSE), por isso
o script le da imagem e reaplica com `--change` -- e confere que o conteudo
sobreviveu antes de liberar a tag. Sem isso a imagem nova sobe sem a
SIGHTOPS_SECRET_KEY e sem o comando de start.

### 10. Espaco em disco

```bash
df -h / /mnt/dados
docker system df
```

O build cache cresce rapido (chegou a 41 GB). `docker builder prune -f` recupera
sem risco. Ja `docker image prune -a` apaga tags de rollback — nao rode sem o
usuario decidir.

### 11. Container que nenhum compose recria

O `docker-compose.production.yml` do v3 sobe 11 dos 22 containers. Outros vêm de
composes próprios (`sightops-prod-nginx`, `olt-telegram-bot`, Evolution). E cinco
**não existiam em arquivo nenhum** até 30/09/2026: `sightops-tls` (HTTPS na 443),
`sightops-nginx`, `sightops-tunnel`, `sightops-lpr-ocr` e `go2rtc`.

```bash
docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' <container>
```

Vazio = criado à mão. Eles sobrevivem a reboot (`restart: unless-stopped`), então
não incomodam no dia a dia — **o risco é remoção**: portas, volumes e comando
moram só em `/var/lib/docker`. O pior caso era o `sightops-tunnel`, cujo token do
Cloudflare existia apenas na linha de comando do container: sem ele o site não
responde pela internet e não há onde consultar o valor.

Hoje os cinco estão descritos em `deploy/compose/docker-compose.extras.yml`,
gerado a partir do que estava **rodando** (não de memória). Esse arquivo é para
reconstruir, não para operar: subir com os containers no ar os recria.

O token não fica lá — vem de `CLOUDFLARE_TUNNEL_TOKEN` no `.env.v3`, que não é
versionado. **Se criar um container à mão, descreva no extras.yml na mesma hora**,
senão o bloco 11 acusa e alguém vai ter que descobrir a configuração de novo.

### 12. O backup leva o que não é do compose

Banco e `.env.v3` recriam o núcleo do v3, mas não o TLS, o túnel nem os proxies.
O backup ganhou um `v3-extras-*.tar.gz` com a definição dos cinco containers, os
certificados da CA (`/home/central/sightops-ca`, fora de qualquer volume), o
`/opt/sightops/go2rtc` e a fonte do LPR.

```bash
E=$(ls -1t /mnt/dados/backups/sightops-db/diario/v3-extras-*.tar.gz | head -1)
tar tzf "$E" | head -20
stat -c '%a' "$E"      # tem que ser 600
```

**O 600 não é zelo: o JSON de definição guarda o token do túnel em claro.** Foi
assim que ele apareceu durante a extração — o filtro de segredo olhava variáveis
de ambiente e o token estava no `command`.

## Como reportar

O usuario quer saber duas coisas: **pode dar push?** e **se reiniciar, perde
algo?** Responda nessa ordem, com numero.

Uma tabela dos doze itens e o resultado de cada, depois os commits para subir e
o comando de push. Se algum item divergir, diga **o que se perderia** em
linguagem de operacao, nao de arquivo: nao "camera_pdf_report.py so existe no
container", e sim "o relatorio volta a ser foto no proximo restart".

## Erros que ja cometi aqui

**Comparar diretorio por tamanho.** Diretorio ocupa espaco proprio, que varia
com quantas entradas ja teve. Somar isso acusou "copia incompleta" com 1590
arquivos identicos e 4096 bytes de diferenca. Conte so arquivos regulares.

**Construir imagem copiando do git por cima do que rodava.** Se o container
tiver codigo que o git nao tem, o `COPY` apaga. Antes de qualquer build,
execute o bloco 3. Construir **a partir da imagem que esta no ar** preserva o
resto — ver `[[sightops-imagem-parte-da-que-esta-no-ar]]`.

**Confiar no codigo de saida do `docker stop`** quando o container demora a
sair. Confira `docker inspect -f '{{.State.Status}}'` depois.

**Reusar numero de `?v=` no asset.** So fura o Cloudflare com numero inedito;
reusar serve JS velho com HTML novo e voce conclui que a correcao nao funcionou.

**Heredoc grande via plink.** Acima de ~100 linhas o shell local quebra com
`unexpected EOF`. Escreva o arquivo localmente e mande com `pscp`.

## Relacionado

`[[sightops-deploy-model]]`, `[[sightops-deploy-producao-real]]`,
`[[v3-deploy-release-stack]]`, `[[sightops-backup-v3]]`,
`[[sightops-servidor-hdd-gargalo]]`, `[[feedback-persistir-no-compose]]`,
skill `sightops-bug-producao`.
