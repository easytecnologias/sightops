#!/bin/sh
# Instala o coletor do SightOps no caixa (Ubuntu, Python 3).
# Uso (como root):  sh instalar.sh <url do SightOps> <id do caixa> <token> [pasta] [estacao]
#   ex.: sh instalar.sh https://sightops.exemplo.com.br 1a2b3c... pdv_xxxx /home/rpdv/frente/Cm 1
# Nao mexe na ponte do gravador nem em nenhum outro servico do caixa.
set -eu

URL_BASE="${1:?informe a URL do SightOps}"
CAIXA="${2:?informe o id do caixa}"
TOKEN="${3:?informe o token do caixa}"
PASTA="${4:-/home/rpdv/frente/Cm}"
ESTACAO="${5:-1}"
DIR="$(cd "$(dirname "$0")" && pwd)"

[ "$(id -u)" = "0" ] || { echo "rode como root (sudo)"; exit 1; }
command -v python3 >/dev/null || { echo "python3 nao encontrado"; exit 1; }
id rpdv >/dev/null 2>&1 || { echo "usuario rpdv nao existe neste caixa"; exit 1; }
[ -d "$PASTA" ] || { echo "pasta do PDV nao existe: $PASTA"; exit 1; }

install -d -m 755 /opt/sightops-pdv
install -m 644 "$DIR/sightops_pdv_coletor.py" /opt/sightops-pdv/sightops_pdv_coletor.py
install -d -m 750 -o rpdv -g rpdv /etc/sightops-pdv /var/lib/sightops-pdv

umask 077
cat > /etc/sightops-pdv/coletor.json <<EOF
{"url": "${URL_BASE%/}/api/pdv/coletor/lote", "caixa": "$CAIXA", "token": "$TOKEN",
 "pasta": "$PASTA", "estacao": $ESTACAO}
EOF
chown rpdv:rpdv /etc/sightops-pdv/coletor.json
chmod 600 /etc/sightops-pdv/coletor.json

install -m 644 "$DIR/sightops-pdv-coletor.service" /etc/systemd/system/sightops-pdv-coletor.service
systemctl daemon-reload
systemctl enable --now sightops-pdv-coletor
sleep 3
systemctl --no-pager --lines=5 status sightops-pdv-coletor || true
echo "Pronto. Acompanhe com: journalctl -u sightops-pdv-coletor -f"
