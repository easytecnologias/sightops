#!/bin/sh
# SightOps - roteamento isolado por conector (tabelas individuais). Idempotente.
# NAO grava a chave privada: le de wg-sightops.conf em runtime.
set -eu
KEY=$(awk -F'=' 'tolower($1) ~ /privatekey/ {sub(/^[^=]*=/,""); gsub(/^[ \t]+|[ \t]+$/,""); print; exit}' /etc/wireguard/wg-sightops.conf)
echo 2 > /proc/sys/net/ipv4/conf/all/rp_filter 2>/dev/null || true
apply() {
  IF=$1; PORT=$2; SRV=$3; TABLE=$4; PREF=$5; PEER=$6; shift 6
  CSV=$(echo "$*" | tr ' ' ',')
  ip link show "$IF" >/dev/null 2>&1 || ip link add "$IF" type wireguard
  printf '%s\n' "$KEY" | wg set "$IF" listen-port "$PORT" private-key /dev/stdin
  wg set "$IF" peer "$PEER" allowed-ips "$CSV"
  ip addr replace "$SRV" dev "$IF"; ip link set "$IF" up
  echo 2 > /proc/sys/net/ipv4/conf/"$IF"/rp_filter 2>/dev/null || true
  ip rule del pref "$PREF" 2>/dev/null || true
  ip rule add from "${SRV%/*}" table "$TABLE" pref "$PREF"
  for c in $*; do ip route replace "$c" dev "$IF" table "$TABLE"; done
}
apply wgc1 52001 10.201.0.2/31 1001 10001 "VURW8XB1OEVfOEWIQEpxLMpgFj0/+sMvpfqgjwzno0o=" 10.250.0.2/32 192.168.10.0/24
apply wgc2 52002 10.201.0.4/31 1002 10002 "liumIl66q7nuxj6Bwzz9I9+5QN92qWcfSt4bBLgkOQI=" 10.250.0.3/32 172.16.16.0/20 192.168.10.0/24
