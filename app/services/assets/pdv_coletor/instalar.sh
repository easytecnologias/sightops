#!/bin/sh
# Instala o coletor do SightOps no caixa (Ubuntu, Python 3). Normalmente quem roda
# e o proprio SightOps, pelo tunel do conector (Configuracoes > Ponto de venda).
# Uso (como root):
#   sh instalar.sh --config <coletor.json>      # SightOps: token num arquivo 600, nunca na linha de comando
#   sh instalar.sh <url> <id do caixa> <token> [pasta] [estacao]   # manual
# Instala tambem o gerador do Espiao: so escreve o Espiao do dia quando o caixa
# nao grava o seu (estacao com o Espiao desligado); senao fica parado.
# Nao mexe na ponte do gravador nem em nenhum outro servico do caixa.
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
[ "$(id -u)" = "0" ] || { echo "rode como root (sudo)"; exit 1; }
command -v python3 >/dev/null || { echo "python3 nao encontrado"; exit 1; }
id rpdv >/dev/null 2>&1 || { echo "usuario rpdv nao existe neste caixa"; exit 1; }

umask 077
install -d -m 750 -o rpdv -g rpdv /etc/sightops-pdv /var/lib/sightops-pdv
if [ "${1:-}" = "--config" ]; then
  CONFIG="${2:?informe o arquivo de configuracao}"
  python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); assert all(c.get(k) for k in ("url","caixa","token","pasta"))' "$CONFIG" \
    || { echo "configuracao invalida"; exit 1; }
  install -m 600 -o rpdv -g rpdv "$CONFIG" /etc/sightops-pdv/coletor.json
else
  # o JSON sai do python (escape correto), e nao de texto colado
  python3 -c 'import json,sys
u,c,t,p,e=sys.argv[1:6]
json.dump({"url": u.rstrip("/") + "/api/pdv/coletor/lote", "caixa": c, "token": t, "pasta": p, "estacao": int(e)},
          open("/etc/sightops-pdv/coletor.json", "w"))' \
    "${1:?informe a URL do SightOps}" "${2:?informe o id do caixa}" "${3:?informe o token do caixa}" \
    "${4:-/home/rpdv/frente/Cm}" "${5:-1}"
  chown rpdv:rpdv /etc/sightops-pdv/coletor.json
  chmod 600 /etc/sightops-pdv/coletor.json
fi
PASTA="$(python3 -c 'import json; print(json.load(open("/etc/sightops-pdv/coletor.json"))["pasta"])')"
[ -d "$PASTA" ] || { echo "pasta do PDV nao existe: $PASTA"; exit 1; }

install -d -m 755 /opt/sightops-pdv
install -m 644 "$DIR/sightops_pdv_coletor.py" /opt/sightops-pdv/sightops_pdv_coletor.py
install -m 644 "$DIR/sightops-pdv-coletor.service" /etc/systemd/system/sightops-pdv-coletor.service
if [ -f "$DIR/sightops_pdv_espiao.py" ]; then
  install -m 644 "$DIR/pdv_cm.py" /opt/sightops-pdv/pdv_cm.py
  install -m 644 "$DIR/sightops_pdv_espiao.py" /opt/sightops-pdv/sightops_pdv_espiao.py
  install -m 644 "$DIR/sightops-pdv-espiao.service" /etc/systemd/system/sightops-pdv-espiao.service
fi
systemctl daemon-reload
systemctl enable sightops-pdv-coletor >/dev/null 2>&1
systemctl restart sightops-pdv-coletor
if [ -f /etc/systemd/system/sightops-pdv-espiao.service ]; then
  systemctl enable sightops-pdv-espiao >/dev/null 2>&1
  systemctl restart sightops-pdv-espiao
fi
sleep 3
systemctl --no-pager --lines=5 status sightops-pdv-coletor || true
systemctl --no-pager --lines=3 status sightops-pdv-espiao 2>/dev/null || true
echo "Pronto. Acompanhe com: journalctl -u sightops-pdv-coletor -f"
