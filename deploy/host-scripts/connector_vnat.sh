#!/bin/sh
# SightOps - NAT 1:1 por conector (IP virtual -> real + origem isolada). Idempotente.
PATH=/usr/sbin:/sbin:/usr/bin:/bin:$PATH
IPT=$(command -v iptables || echo /usr/sbin/iptables)
vnat() {
  V=$1; REAL=$2; IF=$3; TABLE=$4; SRC=$5; MARK=$6; PREF=$7
  $IPT -t mangle -C PREROUTING -d "$V" -j MARK --set-mark "$MARK" 2>/dev/null || $IPT -t mangle -A PREROUTING -d "$V" -j MARK --set-mark "$MARK"
  $IPT -t nat -C PREROUTING -d "$V" -j NETMAP --to "$REAL" 2>/dev/null || $IPT -t nat -A PREROUTING -d "$V" -j NETMAP --to "$REAL"
  $IPT -t nat -C POSTROUTING -o "$IF" -j SNAT --to-source "$SRC" 2>/dev/null || $IPT -t nat -I POSTROUTING 1 -o "$IF" -j SNAT --to-source "$SRC"
  $IPT -C DOCKER-USER -o "$IF" -j ACCEPT 2>/dev/null || $IPT -I DOCKER-USER -o "$IF" -j ACCEPT
  $IPT -C DOCKER-USER -i "$IF" -j ACCEPT 2>/dev/null || $IPT -I DOCKER-USER -i "$IF" -j ACCEPT
  ip rule del fwmark "$MARK" 2>/dev/null || true
  ip rule add fwmark "$MARK" table "$TABLE" pref "$PREF"
}
vnat 10.208.0.0/24  192.168.10.0/24 wgc1 1001 10.201.0.2 0x5101 20001
vnat 10.208.64.0/24 192.168.10.0/24 wgc2 1002 10.201.0.4 0x5102 20002
echo "IPT=$IPT"
echo "== NETMAP =="; $IPT -t nat -S PREROUTING | grep NETMAP
echo "== MARK =="; $IPT -t mangle -S PREROUTING | grep 0x510
echo "== ip rule =="; ip rule show | grep -E "0x510|2000[12]"
vnat 10.208.2.2/32  10.250.0.2/32  wgc1 1001 10.201.0.2 0x5101 20001
vnat 10.208.65.3/32 10.250.0.3/32  wgc2 1002 10.201.0.4 0x5102 20002

