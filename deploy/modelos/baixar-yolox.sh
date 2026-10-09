#!/bin/sh
# Instala o detector da Investigacao (YOLOX, Megvii, licenca Apache 2.0) no
# volume de dados do v3: /app/data/modelos/yolox_m.onnx dentro do container.
#
# Por que no volume e nao no git/imagem: sao 101 MB que nao mudam; no volume
# sobrevivem a recreate sem engordar cada imagem nova.
#
# Uso (no servidor):  sh deploy/modelos/baixar-yolox.sh [container]
set -eu
CONTAINER="${1:-sightops-v3-api}"
MODELO=yolox_m
URL="https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/${MODELO}.onnx"
# sha256 conferido no download de 09/10/2026 (release 0.1.1rc0)
SHA="21ff6cfdeb53b013bac2249599e55f00bff3cfdfdab37ed7a4620818c1d15b3f"
TMP="/tmp/${MODELO}.onnx"

if docker exec "$CONTAINER" test -s "/app/data/modelos/${MODELO}.onnx"; then
  ATUAL=$(docker exec "$CONTAINER" sha256sum "/app/data/modelos/${MODELO}.onnx" | cut -d' ' -f1)
  if [ "$ATUAL" = "$SHA" ]; then echo "ja instalado e conferido: ${MODELO}"; exit 0; fi
  echo "arquivo existente com sha diferente -- substituindo"
fi

[ -s "$TMP" ] && [ "$(sha256sum "$TMP" | cut -d' ' -f1)" = "$SHA" ] || curl -fsSL -o "$TMP" "$URL"
GOT=$(sha256sum "$TMP" | cut -d' ' -f1)
if [ "$GOT" != "$SHA" ]; then
  echo "ERRO: sha256 nao confere ($GOT) -- nao instalado"; exit 1
fi
docker exec "$CONTAINER" mkdir -p /app/data/modelos
docker cp "$TMP" "$CONTAINER:/app/data/modelos/${MODELO}.onnx"
docker exec "$CONTAINER" sha256sum "/app/data/modelos/${MODELO}.onnx"
echo "instalado: ${MODELO} (licenca Apache 2.0)"
