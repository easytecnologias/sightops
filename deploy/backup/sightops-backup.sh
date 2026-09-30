#!/bin/bash
# Backup do SightOps v3 (producao).
#
# Roda como o usuario 'central' (que esta no grupo docker, entao nao precisa
# de root). Guarda tres coisas, porque nenhuma delas sozinha reconstroi o
# sistema:
#
#   1. o banco Postgres        -- usuarios, tenants, controle de acesso, telemetria
#   2. o volume /app/data      -- o INVENTARIO DE CAMERAS mora aqui, em JSON, nao
#                                 no banco; e as fotos dos snapshots
#   3. .env.v3 + compose       -- a SIGHTOPS_SECRET_KEY decifra as senhas das OLTs.
#                                 Sem ela o backup do banco e ilegivel.
#
# O volume pesa ~330MB por causa das fotos, entao ele so entra por inteiro no
# backup semanal; no diario vai so a configuracao (os .json), que e o que muda.
set -uo pipefail

# Disco SEPARADO do sistema (/dev/sdb1 montado em /mnt/dados). Backup no mesmo
# disco dos dados protege contra erro humano, mas nao contra o disco morrer --
# e os dois aqui sao HD mecanico. Ver [[sightops-servidor-hdd-gargalo]].
DEST=/mnt/dados/backups/sightops-db
LOG=$DEST/backup.log

# Se o disco de backup nao estiver montado, o caminho ainda existe (como pasta
# vazia no disco do sistema) e o backup iria em silencio para o lugar errado,
# enchendo o disco da raiz. Melhor falhar alto.
if ! findmnt /mnt/dados >/dev/null 2>&1; then
  echo "$(date +'%F %T') ERRO: /mnt/dados nao esta montado -- backup cancelado" \
    >> /home/central/backups/backup-FALHOU.log
  exit 1
fi
TS=$(date +%Y%m%d-%H%M%S)
DIA_SEMANA=$(date +%u)          # 7 = domingo
MANTER_DIARIOS=14
MANTER_SEMANAIS=8

mkdir -p "$DEST"/{diario,semanal} || exit 1

log() { echo "$(date +'%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
falhou=0

log "=== inicio $TS ==="

# --- 1. banco -----------------------------------------------------------
db=$DEST/diario/v3-db-$TS.sql.gz
if docker exec sightops-v3-postgres pg_dump -U sightops_prod -d sightops_prod \
     --no-owner 2>>"$LOG" | gzip -6 > "$db"; then
  if gzip -t "$db" 2>/dev/null && [ "$(stat -c%s "$db")" -gt 1000000 ]; then
    log "banco OK: $(basename "$db") ($(du -h "$db" | cut -f1))"
  else
    log "ERRO: dump do banco saiu corrompido ou pequeno demais -- apagando"
    rm -f "$db"; falhou=1
  fi
else
  log "ERRO: pg_dump falhou"; rm -f "$db"; falhou=1
fi

# --- 2. configuracao (env + compose) ------------------------------------
# Vai junto em TODO backup: sem a chave, o dump do banco nao serve de nada.
cfg=$DEST/diario/v3-config-$TS.tar.gz
# O .env.v3 mora no RELEASE (o que esta no ar), nao no repositorio git.
# Apontar para o repo funcionou por acidente enquanto havia uma copia solta
# la dentro; quando ela saiu, o backup passou a falhar so nesta parte, todo
# dia, sem que ninguem visse. Conferir antes do tar faz o erro dizer QUAL
# arquivo faltou, em vez de repetir o mesmo engano em silencio.
SRC_CFG=/home/central/sightops-v3-release
faltando=""
for f in .env.v3 docker-compose.production.yml; do
  [ -f "$SRC_CFG/$f" ] || faltando="$faltando $f"
done
if [ -n "$faltando" ]; then
  log "ERRO: configuracao nao encontrada em $SRC_CFG:$faltando"; falhou=1
elif tar czf "$cfg" -C "$SRC_CFG" \
     .env.v3 docker-compose.production.yml 2>>"$LOG"; then
  chmod 600 "$cfg"
  log "config OK: $(basename "$cfg")"
else
  log "ERRO: falhou o tar da configuracao"; falhou=1
fi

# --- 2b. o que NAO esta em compose nenhum -------------------------------
# Cinco containers (sightops-tls, sightops-nginx, sightops-tunnel,
# sightops-lpr-ocr, go2rtc) foram criados a mao e nao existiam em arquivo
# nenhum ate 30/09/2026: portas, volumes e comandos moravam so dentro de
# /var/lib/docker. Com banco e .env.v3 o nucleo do v3 volta, mas o site nao
# responderia na internet nem em HTTPS -- e nao haveria onde consultar como
# eram. Aqui vao a definicao deles, os certificados da CA (que ficam fora de
# qualquer volume) e a config do go2rtc legado.
extras=$DEST/diario/v3-extras-$TS.tar.gz
tmp_extras=$(mktemp -d)
# O `docker inspect` guarda o token do tunnel em claro no comando -- por isso
# o tar inteiro fica 600, como o da configuracao.
docker inspect sightops-tls sightops-nginx sightops-tunnel sightops-lpr-ocr go2rtc   > "$tmp_extras/containers-sem-compose.json" 2>>"$LOG" || true
for extra in /home/central/sightops-ca /opt/sightops/go2rtc; do
  [ -e "$extra" ] && cp -a "$extra" "$tmp_extras/" 2>>"$LOG"
done
for extra in /home/central/sightops-v3/deploy/compose/docker-compose.extras.yml              /home/central/lpr_ocr_teste; do
  [ -e "$extra" ] && cp -a "$extra" "$tmp_extras/" 2>>"$LOG"
done
if tar czf "$extras" -C "$tmp_extras" . 2>>"$LOG"; then
  chmod 600 "$extras"
  log "extras OK: $(basename "$extras") ($(du -h "$extras" | cut -f1))"
else
  log "ERRO: falhou o tar dos extras"; falhou=1
fi
rm -rf "$tmp_extras"

# --- 3. inventario (os JSON do volume, sem as fotos) --------------------
inv=$DEST/diario/v3-inventario-$TS.tar.gz
# As exclusoes tem que vir ANTES dos caminhos: o tar as trata como posicionais
# e ignora em silencio o que vier depois dos argumentos.
if docker exec sightops-v3-api tar czf - \
     --exclude='*.jpg' --exclude='*.jpeg' --exclude='*.png' --exclude='*.webp' \
     -C /app/data \
     $(docker exec sightops-v3-api sh -c 'cd /app/data && ls *.json 2>/dev/null' | tr '\n' ' ') \
     tenants \
     > "$inv" 2>>"$LOG" && [ "$(stat -c%s "$inv")" -gt 10000 ]; then
  log "inventario OK: $(basename "$inv") ($(du -h "$inv" | cut -f1))"
else
  log "ERRO: falhou o inventario"; rm -f "$inv"; falhou=1
fi

# --- 4. volume completo, com as fotos: so aos domingos ------------------
if [ "$DIA_SEMANA" = "7" ]; then
  vol=$DEST/semanal/v3-volume-$TS.tar.gz
  # Imagem que JA existe no servidor: um backup nao pode depender de ter
  # internet para baixar imagem as 3h30 da manha.
  docker run --rm \
    -v sightops-v3-release_sightops_v3_data:/d:ro \
    -v "$DEST/semanal":/saida postgres:17-alpine \
    tar czf "/saida/$(basename "$vol")" -C /d . 2>>"$LOG"
  rc=$?
  # O app reescreve .json o tempo todo, entao o tar quase sempre encontra um
  # arquivo temporario que sumiu no meio da copia e sai com 1. Isso NAO e
  # backup ruim -- so o 2 (erro fatal) e. Quem decide e o teste do gzip.
  if [ $rc -le 1 ] && gzip -t "$vol" 2>/dev/null \
     && [ "$(stat -c%s "$vol")" -gt 50000000 ]; then
    [ $rc = 1 ] && log "aviso: algum arquivo mudou durante a copia (normal)"
    log "volume semanal OK: $(basename "$vol") ($(du -h "$vol" | cut -f1))"
  else
    log "ERRO: falhou o volume semanal (tar=$rc)"; rm -f "$vol"; falhou=1
  fi
fi

# --- 5. limpeza: so apaga se o backup de hoje deu certo -----------------
if [ "$falhou" = "0" ]; then
  for tipo in v3-db v3-config v3-inventario v3-extras; do
    ls -t "$DEST"/diario/$tipo-*.* 2>/dev/null | tail -n +$((MANTER_DIARIOS+1)) | xargs -r rm -f
  done
  ls -t "$DEST"/semanal/v3-volume-*.tar.gz 2>/dev/null | tail -n +$((MANTER_SEMANAIS+1)) | xargs -r rm -f
  log "limpeza feita (guardando $MANTER_DIARIOS diarios / $MANTER_SEMANAIS semanais)"
else
  log "NAO apaguei nada de antigo: o backup de hoje teve falha"
fi

log "espaco livre: $(df -h / | tail -1 | awk '{print $4}')"
log "=== fim (falhas: $falhou) ==="
exit $falhou
