#!/bin/bash
# Move os volumes dos bancos para o segundo disco (/mnt/dados), dividindo o I/O
# entre os dois HDs mecanicos.
#
# METODO: bind mount, nao recriacao de volume. O volume Docker continua com o
# mesmo nome e o mesmo caminho em /var/lib/docker/volumes/<nome>/_data -- so que
# esse caminho passa a ser um espelho do diretorio no outro disco. Assim o
# docker-compose NAO muda e nenhum container precisa ser recriado, o que aqui
# importa muito: ha correcoes que vivem so na imagem em execucao do v3, e um
# recreate as perderia.
#
# SEGURANCA: o diretorio original vira _data.old e NAO e apagado por este
# script. Se algo der errado, desfazer e: umount, apagar _data, renomear
# _data.old de volta.
set -uo pipefail
export PATH=/sbin:/usr/sbin:/usr/bin:/bin:$PATH

DESTINO_BASE=/mnt/dados/docker-volumes
VOLUMES_DIR=/var/lib/docker/volumes

# volume : containers que precisam parar (na ordem de parada)
declare -A ALVOS=()
case "${1:-}" in
  zabbix)
    ALVOS["sightops-v3-release_zabbix_v3_postgres"]="zabbix-v3-server zabbix-v3-web zabbix-v3-postgres" ;;
  sightops)
    ALVOS["sightops-v3-release_sightops_v3_postgres"]="sightops-v3-api sightops-v3-postgres" ;;
  *)
    echo "uso: $0 zabbix|sightops"
    echo "  zabbix   = 4,7 GB, o que mais escreve. Derruba so o monitoramento."
    echo "  sightops = 1,1 GB. Derruba a API do SightOps por alguns minutos."
    echo "Um de cada vez, de proposito: assim uma falha nunca deixa os dois fora."
    exit 1 ;;
esac

findmnt /mnt/dados >/dev/null 2>&1 || { echo "ABORTADO: /mnt/dados nao esta montado"; exit 1; }
mkdir -p "$DESTINO_BASE"

for VOL in "${!ALVOS[@]}"; do
  CONTAINERS="${ALVOS[$VOL]}"
  ORIG="$VOLUMES_DIR/$VOL/_data"
  NOVO="$DESTINO_BASE/$VOL"

  echo ""
  echo "=================================================================="
  echo "VOLUME: $VOL"
  echo "=================================================================="

  [ -d "$ORIG" ] || { echo "  PULANDO: $ORIG nao existe"; continue; }
  if mountpoint -q "$ORIG"; then echo "  PULANDO: ja e bind mount"; continue; fi

  echo "  tamanho: $(du -sh "$ORIG" 2>/dev/null | cut -f1)"

  echo "  parando containers: $CONTAINERS"
  for c in $CONTAINERS; do
    docker stop -t 60 "$c" >/dev/null 2>&1
    # O codigo de saida do `docker stop` nao e confiavel quando o container
    # demora a sair; quem vale e o estado real depois.
    est=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null)
    if [ "$est" = "exited" ] || [ "$est" = "created" ] || [ -z "$est" ]; then
      echo "    parado: $c"
    else
      echo "    ABORTADO: $c continua '$est' -- nao da para copiar banco em uso"
      for r in $(echo "$CONTAINERS" | tr ' ' '\n' | tac); do docker start "$r" >/dev/null 2>&1; done
      continue 2
    fi
  done

  echo "  copiando para o disco novo..."
  rm -rf "$NOVO"
  if ! cp -a "$ORIG" "$NOVO"; then
    echo "  ERRO na copia -- religando containers e abortando este volume"
    for c in $(echo "$CONTAINERS" | tr ' ' '\n' | tac); do docker start "$c" >/dev/null 2>&1; done
    continue
  fi

  # Confere por CONTAGEM e por TAMANHO: cp que morre no meio (disco cheio,
  # por exemplo) deixa uma copia parcial que parece valida por fora.
  #
  # So ARQUIVOS REGULARES entram na conta. Diretorio ocupa espaco proprio, que
  # depende de quantas entradas ele ja teve na vida -- copiar para um
  # filesystem novo quase sempre da alguns KB de diferenca so nos diretorios.
  # Somar isso fazia a verificacao acusar copia incompleta quando estava
  # perfeita (aconteceu: 4096 bytes de diferenca, 1590 arquivos identicos).
  n_o=$(find "$ORIG" -type f | wc -l);  n_n=$(find "$NOVO" -type f | wc -l)
  b_o=$(find "$ORIG" -type f -printf '%s\n' | awk '{s+=$1} END{print s+0}')
  b_n=$(find "$NOVO" -type f -printf '%s\n' | awk '{s+=$1} END{print s+0}')
  echo "    origem : $n_o arquivos, $b_o bytes"
  echo "    destino: $n_n arquivos, $b_n bytes"
  if [ "$n_o" != "$n_n" ] || [ "$b_o" != "$b_n" ]; then
    echo "  ERRO: copia incompleta -- desfazendo e religando"
    rm -rf "$NOVO"
    for c in $(echo "$CONTAINERS" | tr ' ' '\n' | tac); do docker start "$c" >/dev/null 2>&1; done
    continue
  fi
  echo "    copia confere"

  # Troca: guarda o original, poe um diretorio vazio no lugar e espelha o novo.
  mv "$ORIG" "${ORIG}.old"
  mkdir -p "$ORIG"
  chown --reference="${ORIG}.old" "$ORIG" 2>/dev/null || true
  mount --bind "$NOVO" "$ORIG"
  mountpoint -q "$ORIG" && echo "  montado: $ORIG -> $NOVO" || { echo "  ERRO no mount"; continue; }

  # fstab para sobreviver ao reboot. nofail pelo mesmo motivo de sempre: um
  # problema aqui nao pode impedir o servidor de ligar.
  sed -i "\|$ORIG|d" /etc/fstab
  echo "$NOVO  $ORIG  none  bind,nofail  0  0" >> /etc/fstab

  echo "  religando containers..."
  for c in $(echo "$CONTAINERS" | tr ' ' '\n' | tac); do
    docker start "$c" >/dev/null 2>&1 && echo "    subiu: $c" || echo "    ERRO ao subir: $c"
  done
done

echo ""
echo "=================================================================="
echo "RESUMO"
echo "=================================================================="
echo "--- bind mounts ativos ---"
mount | grep "docker/volumes" | sed 's/^/  /' || echo "  nenhum"
echo "--- fstab ---"
grep "docker-volumes" /etc/fstab | sed 's/^/  /' || echo "  nenhum"
echo "--- espaco ---"
df -h / /mnt/dados | sed 's/^/  /'
echo ""
echo "Os diretorios originais foram guardados como _data.old e NAO foram"
echo "apagados. Confira que tudo funciona antes de remove-los."
cp -a /etc/fstab "/etc/fstab.bak-volumes-$(date +%Y%m%d-%H%M%S)"
