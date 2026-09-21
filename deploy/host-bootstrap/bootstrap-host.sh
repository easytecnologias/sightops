#!/bin/bash
# SightOps v3 -- bootstrap de HOST para um servidor NOVO. Rodar UMA vez, com sudo.
# Deixa a maquina pronta para o "docker compose up" cuidar do resto (app, zabbix,
# provisioner). Tudo que e per-conector se reconstroi sozinho do connectors.json.
#
# Pre-requisitos que voce traz do servidor antigo (segredos -- NAO ficam no git):
#   1) os volumes docker (sightops_v3_data, sightops_v3_postgres, ...)
#   2) o /etc/wireguard/wg-sightops.conf (o "portao" WireGuard + a chave privada
#      que as interfaces wgc<N> reusam)
#   3) o .env.v3
set -e

echo "== 1. rp_filter frouxo (roteamento por origem) =="
install -D -m 0644 "$(dirname "$0")/99-sightops-wgc.conf" /etc/sysctl.d/99-sightops-wgc.conf
sysctl --system >/dev/null
echo "   all.rp_filter = $(cat /proc/sys/net/ipv4/conf/all/rp_filter)"

echo "== 2. tunel base wg-sightops (o portao publico :51820) =="
if [ ! -f /etc/wireguard/wg-sightops.conf ]; then
  echo "   !! FALTA /etc/wireguard/wg-sightops.conf -- copie do servidor antigo antes de continuar."
  exit 1
fi
systemctl enable --now wg-quick@wg-sightops
echo "   wg-sightops: $(systemctl is-active wg-quick@wg-sightops)"

echo "== 3. pronto =="
echo "   Agora: cd no release e 'docker compose --env-file .env.v3 up -d'."
echo "   O sightops-v3-iso-provisioner recria wgc<N> + vnat de TODOS os conectores"
echo "   (migrados e novos) a partir do connectors.json. Nada de script por cliente."
echo "   Ultimo passo externo: apontar o forward da borda (51820 + 52000-52099) pro IP novo."
