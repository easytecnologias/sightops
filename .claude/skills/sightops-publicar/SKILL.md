---
name: sightops-publicar
description: Publica uma correcao do SightOps v3 em producao (backend por imagem, frontend por bind mount) sem perder trabalho de outro agente e sem servir JS velho pelo cache. Use quando o usuario pedir para publicar, subir, fazer deploy ou "colocar no ar".
disable-model-invocation: true
---

# Publicar no SightOps v3

Producao nao vem do git: o backend e a imagem `sightops-prod-api:<tag>` rodando no
container `sightops-v3-api`, o frontend e o bind mount
`/home/central/sightops-v3-release/frontend`. Os erros que esta receita evita
aconteceram de verdade:

- copiar o arquivo do git por cima apagou 3 h de trabalho de outro agente;
- `docker cp` sem `commit` sumiu no recreate (o relatorio em PDF voltou a ser foto);
- `?v=` reutilizado serviu JS velho e pareceu que a correcao nao funcionava.

## 1. Partir do que esta no ar

```bash
docker cp sightops-v3-api:/app/app/services/X.py /tmp/X.py   # base = producao
# aplique SO o seu diff em /tmp/novo_X.py (script com assert de 1 ocorrencia)
docker exec sightops-v3-api python -m py_compile /tmp/novo_X.py 2>/dev/null || python3 -m py_compile /tmp/novo_X.py
```

Compare o arquivo do container com o git antes (`md5sum`). Se diferem, alguem
publicou sem commitar: o seu diff vai em cima do container, nunca do git.

## 2. Comandos para o usuario rodar

Deploy em producao e feito pelo usuario. Entregue pronto para colar, com uma tag
nova `AAAAMMDD-assunto`:

```bash
docker cp /tmp/novo_X.py sightops-v3-api:/app/app/services/X.py
docker restart sightops-v3-api
docker commit sightops-v3-api sightops-prod-api:AAAAMMDD-assunto
cd /home/central/sightops-v3-release
sed -i 's|^CAM_SNAPSHOT_IMAGE=.*|CAM_SNAPSHOT_IMAGE=sightops-prod-api:AAAAMMDD-assunto|' .env.v3
```

Antes: `docker history -q <imagem atual> | wc -l`. Passou de ~110, achatar
primeiro com `deploy/imagem/achatar-imagem.sh`.

## 3. Frontend

- Copie para `/home/central/sightops-v3-release/frontend/...`.
- No `index.html`, troque o `?v=` **so do arquivo alterado** por um numero maior que
  qualquer um ja usado no arquivo.
- Confirme que a lista de `<script src="js/...">` nao mudou.

## 4. Provar

```bash
docker exec sightops-v3-api md5sum /app/app/services/X.py && md5sum /tmp/novo_X.py
grep ^CAM_SNAPSHOT_IMAGE= /home/central/sightops-v3-release/.env.v3
docker logs --since 5m sightops-v3-api 2>&1 | grep -iE 'traceback|exception'
```

E o numero de producao que motivou a correcao, antes e depois.

## 5. Commitar

Copie do container e do frontend publicado para `/home/central/sightops-v3`,
confira que o diff e so o seu (`git diff --stat`), e faca o commit. O push e do
usuario: `cd /home/central/sightops-v3 && git push origin main`.
