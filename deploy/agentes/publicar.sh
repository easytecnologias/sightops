#!/usr/bin/env bash
# Publica uma correcao do SightOps com as verificacoes na ordem certa.
#
# POR QUE NAO FAZER NA MAO
#
# O deploy daqui tem cinco armadilhas, e todas ja custaram trabalho perdido:
#
#   1. construir a partir de uma tag ANTIGA em vez da que esta no ar apaga o
#      que outro agente publicou;
#   2. construir com codigo que so existe DENTRO do container apaga esse
#      codigo (foi assim que o gerador ReportLab do relatorio se perdeu);
#   3. a imagem empilha uma camada por deploy e o build morre em ~130, sempre
#      na hora de publicar;
#   4. esquecer de subir o ?v= do asset faz o navegador servir o JS velho, e
#      voce conclui que a correcao nao funcionou;
#   5. dois agentes publicando ao mesmo tempo -- o segundo apaga o primeiro.
#
# Este script faz na ordem, sempre. Para em qualquer erro, e solta a trava no
# fim aconteca o que acontecer.
#
# USO
#   publicar.sh <quem> "<assunto-curto>" <arquivo> [arquivo...]
#
# exemplo:
#   publicar.sh claude onu-sync app/main.py app/services/monitoring_service.py
#
# Os arquivos sao caminhos relativos ao repositorio, e precisam ja estar
# COMMITADOS -- publicar codigo nao commitado e como o trabalho some.

set -euo pipefail

REPO=/home/central/sightops-v3
REL=/home/central/sightops-v3-release
API=sightops-v3-api
AQUI="$(cd "$(dirname "$0")" && pwd)"

QUEM=${1:?uso: publicar.sh <quem> "<assunto>" <arquivo> [...]}
ASSUNTO=${2:?uso: publicar.sh <quem> "<assunto>" <arquivo> [...]}
shift 2
[ $# -ge 1 ] || { echo "informe pelo menos um arquivo"; exit 2; }
ARQUIVOS=("$@")

TAG="sightops-prod-api:$(date +%Y%m%d)-${ASSUNTO}"
TMP=$(mktemp -d)
soltar() {
  bash "$AQUI/trava.sh" soltar "$QUEM" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}

echo "=== 0. trava ==="
bash "$AQUI/trava.sh" pegar "$QUEM" "publicar $ASSUNTO" || exit 1
trap soltar EXIT

cd "$REPO"

echo
echo "=== 1. os arquivos estao commitados? ==="
sujos=$(git status --porcelain -- "${ARQUIVOS[@]}" || true)
if [ -n "$sujos" ]; then
  echo "$sujos" | sed 's/^/    /'
  echo "  PARE: commite antes de publicar. Codigo publicado sem commit some no"
  echo "  proximo recreate e ninguem descobre de onde veio."
  exit 1
fi
echo "  todos commitados"

echo
echo "=== 2. existe codigo que SO esta no container? ==="
# Se existir, construir a partir do git apaga esse codigo. E o passo que teria
# evitado a perda do gerador de PDF vetorial.
perigo=0
for f in "${ARQUIVOS[@]}"; do
  case "$f" in *.py) ;; *) continue ;; esac
  a=$(docker exec "$API" md5sum "/app/$f" 2>/dev/null | cut -d' ' -f1 || true)
  b=$(md5sum "$f" 2>/dev/null | cut -d' ' -f1)
  if [ -n "$a" ] && [ "$a" != "$b" ]; then
    echo "    DIVERGE: $f"
    echo "      no container: $a"
    echo "      no git      : $b"
    perigo=1
  fi
done
if [ "$perigo" = 1 ]; then
  echo "  PARE: o container tem versao diferente do git nesses arquivos."
  echo "  Pode ser trabalho de outro agente que nunca virou imagem. Compare"
  echo "  antes (docker exec $API cat /app/<arquivo>) e so entao publique."
  exit 1
fi
echo "  nenhum -- seguro construir a partir do git"

echo
echo "=== 3. base: a imagem que esta NO AR ==="
BASE=$(docker inspect "$API" --format '{{.Config.Image}}')
echo "  base: $BASE"
CAMADAS=$(docker history -q "$BASE" | grep -c .)
echo "  camadas da base: $CAMADAS"
if [ "$CAMADAS" -ge 120 ]; then
  echo "  PARE: perto do limite do Docker (~130). Achate antes:"
  echo "    bash deploy/imagem/achatar-imagem.sh $BASE sightops-prod-api:$(date +%Y%m%d)-achatada"
  exit 1
fi

echo
echo "=== 4. construindo $TAG ==="
for f in "${ARQUIVOS[@]}"; do
  mkdir -p "$TMP/$(dirname "$f")"
  cp "$f" "$TMP/$f"
done
{
  echo "FROM $BASE"
  for f in "${ARQUIVOS[@]}"; do echo "COPY $f /app/$f"; done
} > "$TMP/Dockerfile"
( cd "$TMP" && docker build -q -t "$TAG" . >/dev/null )
echo "  construida ($(docker history -q "$TAG" | grep -c .) camadas)"

echo
echo "=== 5. a aplicacao ainda sobe? ==="
# Import quebrado so aparece aqui. Sem este passo o container sobe, morre, e o
# site fica fora do ar ate alguem perceber.
docker run --rm -e DATABASE_BACKEND=sqlite "$TAG" python -c "import app.main" \
  && echo "  import de app.main OK"

echo
echo "=== 6. asset: subir o ?v= do que mudou ==="
# Numero INEDITO, sempre: reusar um antigo nao fura o cache do Cloudflare e o
# navegador continua servindo o JS velho.
NOVO_V=$(date +%s)
mexeu_front=0
for f in "${ARQUIVOS[@]}"; do
  case "$f" in
    frontend/js/*.js)
      nome=$(basename "$f")
      if grep -q "$nome?v=" "$REL/frontend/index.html" 2>/dev/null; then
        sed -i "s|${nome}?v=[0-9]*|${nome}?v=${NOVO_V}|" "$REL/frontend/index.html"
        echo "  $nome -> ?v=$NOVO_V"
        mexeu_front=1
      fi
      ;;
  esac
done
[ "$mexeu_front" = 0 ] && echo "  nenhum js de frontend nesta publicacao"

echo
echo "=== 7. apontando o .env.v3 ==="
cp -a "$REL/.env.v3" "/mnt/dados/backups/sightops-env/.env.v3.antes-${ASSUNTO}-$(date +%H%M%S)" 2>/dev/null || true
sed -i "s|^CAM_SNAPSHOT_IMAGE=.*|CAM_SNAPSHOT_IMAGE=${TAG}|" "$REL/.env.v3"
( cd "$REL" && docker compose -f docker-compose.production.yml --env-file .env.v3 config -q )
echo "  $TAG  (compose valido)"

echo
echo "=== 8. subindo ==="
( cd "$REL" && docker compose -f docker-compose.production.yml --env-file .env.v3 up -d cam-snapshot-api )

echo
echo "=== 9. conferindo ==="
sleep 8
NOAR=$(docker inspect "$API" --format '{{.Config.Image}}')
EST=$(docker inspect "$API" --format '{{.State.Status}}')
echo "  no ar : $NOAR"
echo "  status: $EST"
[ "$NOAR" = "$TAG" ] || { echo "  ATENCAO: subiu imagem diferente da publicada"; exit 1; }
[ "$EST" = "running" ] || { echo "  ATENCAO: container nao esta running"; exit 1; }
erros=$(docker logs --since 2m "$API" 2>&1 | grep -ciE 'traceback|exception' || true)
echo "  erros no log (2 min): $erros"
[ "${erros:-0}" -gt 0 ] && echo "  olhe: docker logs --since 2m $API"

echo
echo "=== PUBLICADO: $TAG ==="
[ "$mexeu_front" = 1 ] && echo "  avise para dar Ctrl+Shift+R (asset novo: ?v=$NOVO_V)"
echo "  para voltar atras: aponte CAM_SNAPSHOT_IMAGE=$BASE no .env.v3 e suba de novo"
