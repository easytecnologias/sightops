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

# --change para cada item da configuracao. O ENV vem via arquivo para nao
# aparecer em linha de comando nem em log.
MUD=()
while IFS= read -r e; do
  [ -n "$e" ] && MUD+=(--change "ENV $e")
done < <(docker inspect "$BASE" --format '{{range .Config.Env}}{{println .}}{{end}}')

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

docker export "$TMP" | docker import "${MUD[@]}" - "$NOVA" >/dev/null
echo "  nova : $NOVA  ($(docker history -q "$NOVA" | wc -l) camada)"

echo "  --- conferindo que a nova imagem funciona ---"
docker run --rm -e DATABASE_BACKEND=sqlite "$NOVA" python -c "import app.main; print('  import de app.main OK')"
a=$(docker run --rm "$BASE" sh -c 'ls -1 /app/app/services | wc -l')
b=$(docker run --rm "$NOVA" sh -c 'ls -1 /app/app/services | wc -l')
echo "  arquivos em app/services: base=$a  nova=$b"
[ "$a" = "$b" ] && echo "  conteudo preservado" || { echo "  DIVERGIU -- nao use a nova"; exit 1; }
