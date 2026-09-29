#!/usr/bin/env bash
# Trava de publicacao do SightOps -- um agente publica por vez.
#
# POR QUE ISSO EXISTE
#
# Cada correcao e publicada como "FROM a imagem que esta no ar + COPY". Se dois
# agentes fazem isso em paralelo, os DOIS partem da mesma base e o segundo a
# publicar apaga o trabalho do primeiro. Sem erro, sem conflito de merge, sem
# aviso -- a pessoa so descobre dias depois que a correcao sumiu. Ja aconteceu
# neste projeto: "parti de uma imagem anterior e apaguei 3h de trabalho de
# outro agente em producao".
#
# Conflito de git o proprio git avisa. ESTE tipo de perda e silencioso, e e o
# unico que precisa de trava.
#
# USO
#   trava.sh pegar  <quem> "<motivo>"   pega a trava (falha se ocupada)
#   trava.sh soltar <quem>              devolve
#   trava.sh ver                        mostra quem esta com ela
#   trava.sh pegar  <quem> "<motivo>" --forcar   ignora trava velha (>45min)
#
# A trava fica em /tmp de proposito: some no reboot, entao maquina reiniciada
# nunca nasce travada por um agente que nao existe mais.

set -u
LOCK=/tmp/sightops-deploy.lock.d
INFO="$LOCK/dono"
VELHA_MIN=${SIGHTOPS_TRAVA_VELHA_MIN:-45}

agora() { date '+%Y-%m-%d %H:%M:%S'; }

mostrar() {
  if [ ! -d "$LOCK" ]; then
    echo "  livre"
    return 1
  fi
  local quem inicio motivo idade
  quem=$(sed -n '1p' "$INFO" 2>/dev/null || echo "?")
  inicio=$(sed -n '2p' "$INFO" 2>/dev/null || echo "?")
  motivo=$(sed -n '3p' "$INFO" 2>/dev/null || echo "?")
  idade=$(( ( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || date +%s) ) / 60 ))
  echo "  OCUPADA por: $quem"
  echo "  desde      : $inicio  (${idade} min)"
  echo "  motivo     : $motivo"
  [ "$idade" -ge "$VELHA_MIN" ] && echo "  AVISO: trava com mais de ${VELHA_MIN} min -- pode ser resto de agente que caiu"
  return 0
}

case "${1:-}" in
  pegar)
    QUEM=${2:?uso: trava.sh pegar <quem> "<motivo>"}
    MOTIVO=${3:-sem motivo informado}
    FORCAR=${4:-}
    # mkdir e atomico: dois agentes tentando ao mesmo tempo, so um cria.
    if mkdir "$LOCK" 2>/dev/null; then
      printf '%s\n%s\n%s\n' "$QUEM" "$(agora)" "$MOTIVO" > "$INFO"
      echo "  trava pega por $QUEM"
      exit 0
    fi
    echo "  NAO peguei a trava:"
    mostrar
    idade=$(( ( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || date +%s) ) / 60 ))
    if [ "$FORCAR" = "--forcar" ] && [ "$idade" -ge "$VELHA_MIN" ]; then
      echo "  --forcar em trava de ${idade} min: assumindo"
      printf '%s\n%s\n%s\n' "$QUEM" "$(agora)" "$MOTIVO (forcado sobre trava de ${idade}min)" > "$INFO"
      touch "$LOCK"
      exit 0
    fi
    echo
    echo "  Espere terminar, ou confirme com o dono antes de usar --forcar."
    exit 1
    ;;
  soltar)
    QUEM=${2:?uso: trava.sh soltar <quem>}
    if [ ! -d "$LOCK" ]; then
      echo "  ja estava livre"
      exit 0
    fi
    dono=$(sed -n '1p' "$INFO" 2>/dev/null || echo "?")
    if [ "$dono" != "$QUEM" ]; then
      echo "  a trava e de '$dono', nao de '$QUEM' -- nao vou soltar"
      echo "  se ele caiu, use: trava.sh pegar $QUEM \"<motivo>\" --forcar"
      exit 1
    fi
    rm -rf "$LOCK"
    echo "  trava solta por $QUEM"
    ;;
  ver|"")
    mostrar || true
    ;;
  *)
    echo "uso: trava.sh {pegar <quem> \"<motivo>\" [--forcar] | soltar <quem> | ver}"
    exit 2
    ;;
esac
