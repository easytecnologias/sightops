#!/usr/bin/env bash
# Achata a imagem da API: 131 camadas -> 1.
#
# Cada correcao publicada empilha uma camada nova (FROM a anterior + COPY). O
# Docker para em ~130 e o build morre com "max depth exceeded" -- foi o que
# aconteceu agora. export/import junta tudo num sistema de arquivos so.
#
# O import PERDE a configuracao (ENV, CMD, WORKDIR, EXPOSE), entao ela e lida da
# imagem atual e reaplicada com --change. Os segredos que estao embutidos no ENV
# passam por aqui sem nunca serem impressos.
#
# Nao mexe em nada que esta rodando: cria uma tag nova.

set -euo pipefail
BASE=${1:?uso: achata.sh <imagem-base> <imagem-nova>}
NOVA=${2:?uso: achata.sh <imagem-base> <imagem-nova>}

echo "  base : $BASE  ($(docker history -q "$BASE" | wc -l) camadas)"

# --change para a configuracao SEM segredo (WORKDIR, CMD, ENTRYPOINT, EXPOSE).
# O ENV NAO vai por --change: argumento de processo aparece no `ps` de qualquer
# usuario do servidor durante os minutos do export/import -- em 26/10/2026 as
# senhas do banco, do Zabbix e a SIGHTOPS_SECRET_KEY ficaram expostas assim.
# O ENV vai num Dockerfile temporario (umask 077) aplicado depois do import.
MUD=()

WD=$(docker inspect "$BASE" --format '{{.Config.WorkingDir}}')
[ -n "$WD" ] && MUD+=(--change "WORKDIR $WD")

CMD=$(docker inspect "$BASE" --format '{{json .Config.Cmd}}')
[ "$CMD" != "null" ] && MUD+=(--change "CMD $CMD")

EP=$(docker inspect "$BASE" --format '{{json .Config.Entrypoint}}')
[ "$EP" != "null" ] && MUD+=(--change "ENTRYPOINT $EP")

while IFS= read -r p; do
  [ -n "$p" ] && MUD+=(--change "EXPOSE ${p%%/*}")
done < <(docker inspect "$BASE" --format '{{range $k,$v := .Config.ExposedPorts}}{{println $k}}{{end}}')

echo "  itens de configuracao preservados: ${#MUD[@]}"

# Container parado so para servir de fonte ao export.
TMP=$(docker create "$BASE" /bin/true)
echo "  container temporario: ${TMP:0:12}"
trap 'docker rm -f "$TMP" >/dev/null 2>&1 || true' EXIT

PLANA="${NOVA}-plana"
docker export "$TMP" | docker import "${MUD[@]}" - "$PLANA" >/dev/null

# ENV: um ENV so (metadado, nao cria camada de arquivos), com aspas e $ escapados.
DIR=$(umask 077; mktemp -d)
trap 'docker rm -f "$TMP" >/dev/null 2>&1 || true; rm -rf "$DIR"' EXIT
{
  echo "FROM $PLANA"
  printf 'ENV'
  docker inspect "$BASE" --format '{{range .Config.Env}}{{println .}}{{end}}' | while IFS= read -r e; do
    [ -z "$e" ] && continue
    k=${e%%=*}; v=${e#*=}
    v=${v//\\/\\\\}; v=${v//\"/\\\"}; v=${v//\$/\\\$}
    printf ' \\\n  %s="%s"' "$k" "$v"
  done
  echo
} > "$DIR/Dockerfile"
docker build -q -t "$NOVA" "$DIR" >/dev/null
docker rmi "$PLANA" >/dev/null
echo "  nova : $NOVA  ($(docker history -q "$NOVA" | wc -l) entradas no historico, 1 camada de arquivos)"
a_env=$(docker inspect "$BASE" --format '{{range .Config.Env}}{{println .}}{{end}}' | sort | md5sum)
b_env=$(docker inspect "$NOVA" --format '{{range .Config.Env}}{{println .}}{{end}}' | sort | md5sum)
[ "$a_env" = "$b_env" ] && echo "  ENV identico ao da base" || { echo "  ENV DIVERGIU -- nao use a nova"; exit 1; }

echo "  --- conferindo que a nova imagem funciona ---"
docker run --rm -e DATABASE_BACKEND=sqlite "$NOVA" python -c "import app.main; print('  import de app.main OK')"
a=$(docker run --rm "$BASE" sh -c 'ls -1 /app/app/services | wc -l')
b=$(docker run --rm "$NOVA" sh -c 'ls -1 /app/app/services | wc -l')
echo "  arquivos em app/services: base=$a  nova=$b"
[ "$a" = "$b" ] && echo "  conteudo preservado" || { echo "  DIVERGIU -- nao use a nova"; exit 1; }
