#!/bin/sh
# SightOps - barreira de firewall ENTRE clientes. Idempotente; roda como root.
#
# Por que existe: DOCKER-USER tem "-i wgcN -j ACCEPT" e "-o wgcN -j ACCEPT"
# (connector_iso.sh e o provisionamento dos conectores novos). Isso aceita
# QUALQUER encaminhamento que entra ou sai de um tunel de cliente -- inclusive
# de um tunel de cliente para o tunel de OUTRO cliente. Com ip_forward=1 e o
# NETMAP das faixas virtuais (10.208.x/10.209.x) casando por destino, a rede
# de um cliente que roteasse essas faixas pelo tunel alcancaria as cameras de
# outro cliente atravessando o servidor. As tabelas por conector isolam so a
# IDA do SightOps; nao impedem a travessia.
#
# Nenhum uso legitimo cruza dois tuneis: a API sai pela bridge do Docker
# (-i br-*/docker0), que esta barreira nao toca.
#
# As regras de ACCEPT sao (re)inseridas no TOPO do DOCKER-USER por outros
# scripts a qualquer momento, entao o salto para SIGHTOPS-ISO e reafirmado
# na posicao 1 a cada execucao (timer de 1 min + boot).
set -u
PATH=/usr/sbin:/sbin:/usr/bin:/bin:$PATH
IPT=$(command -v iptables || echo /usr/sbin/iptables)

# Interfaces de tunel de cliente: WireGuard isolado (wgc+), rede propria do
# tunel Ruijie isolado (rjc+), OpenVPN do Ruijie antigo
# (tun+) e a rede compartilhada antiga (wg-sightops).
TUNEIS="wgc+ rjc+ tun+ wg-sightops"

$IPT -N SIGHTOPS-ISO 2>/dev/null || true
$IPT -F SIGHTOPS-ISO
for de in $TUNEIS; do
  for para in $TUNEIS; do
    $IPT -A SIGHTOPS-ISO -i "$de" -o "$para" -j DROP
  done
done
$IPT -A SIGHTOPS-ISO -j RETURN

# Salto sempre na posicao 1 (acima de qualquer ACCEPT por interface).
primeira=$($IPT -S DOCKER-USER 2>/dev/null | sed -n 2p)
if [ "$primeira" != "-A DOCKER-USER -j SIGHTOPS-ISO" ]; then
  while $IPT -D DOCKER-USER -j SIGHTOPS-ISO 2>/dev/null; do :; done
  $IPT -I DOCKER-USER 1 -j SIGHTOPS-ISO
fi
