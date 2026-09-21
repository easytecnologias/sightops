#!/bin/sh
# GERADO por sightops_connector_iso_gen.py -- nao editar a mao.
# Isolamento por conector (modelo A): interfaces wgc<N> + tabelas + NAT 1:1 virtual.
set -u
PATH=/usr/sbin:/sbin:/usr/bin:/bin:$PATH
IPT=$(command -v iptables || echo /usr/sbin/iptables)
KEY=$(awk -F'=' 'tolower($1) ~ /privatekey/ {sub(/^[^=]*=/,""); gsub(/^[ \t]+|[ \t]+$/,""); print; exit}' /etc/wireguard/wg-sightops.conf)
echo 2 > /proc/sys/net/ipv4/conf/all/rp_filter 2>/dev/null || true

wg_iface() {  # IF PORT SRV/31 TABLE PREF PEER "allowed,csv"
  IF=$1; PORT=$2; SRV=$3; TABLE=$4; PREF=$5; PEER=$6; ALLOWED=$7
  ip link show "$IF" >/dev/null 2>&1 || ip link add "$IF" type wireguard
  printf '%s\n' "$KEY" | wg set "$IF" listen-port "$PORT" private-key /dev/stdin
  wg set "$IF" peer "$PEER" allowed-ips "$ALLOWED"
  ip addr replace "$SRV" dev "$IF"; ip link set "$IF" up
  echo 2 > /proc/sys/net/ipv4/conf/"$IF"/rp_filter 2>/dev/null || true
  ip rule del pref "$PREF" 2>/dev/null || true
  ip rule add from "${SRV%/*}" table "$TABLE" pref "$PREF"
}
route_add() { ip route replace "$1" dev "$2" table "$3"; }
vnat() {  # VIRT REAL IF TABLE SRC MARK PREF
  V=$1; REAL=$2; IF=$3; TABLE=$4; SRC=$5; MARK=$6; PREF=$7
  $IPT -t mangle -C PREROUTING -d "$V" -j MARK --set-mark "$MARK" 2>/dev/null || $IPT -t mangle -A PREROUTING -d "$V" -j MARK --set-mark "$MARK"
  $IPT -t nat -C PREROUTING -d "$V" -j NETMAP --to "$REAL" 2>/dev/null || $IPT -t nat -A PREROUTING -d "$V" -j NETMAP --to "$REAL"
  $IPT -t nat -C POSTROUTING -o "$IF" -j SNAT --to-source "$SRC" 2>/dev/null || $IPT -t nat -I POSTROUTING 1 -o "$IF" -j SNAT --to-source "$SRC"
  $IPT -C DOCKER-USER -o "$IF" -j ACCEPT 2>/dev/null || $IPT -I DOCKER-USER -o "$IF" -j ACCEPT
  $IPT -C DOCKER-USER -i "$IF" -j ACCEPT 2>/dev/null || $IPT -I DOCKER-USER -i "$IF" -j ACCEPT
  ip rule del fwmark "$MARK" 2>/dev/null || true
  ip rule add fwmark "$MARK" table "$TABLE" pref "$PREF"
}

# ---- PORTO REAL DO COLEGIO (a04555f5bcb652cb) index 1 ----
wg_iface wgc1 52001 10.201.0.2/31 1001 10001 "VURW8XB1OEVfOEWIQEpxLMpgFj0/+sMvpfqgjwzno0o=" "10.250.0.2/32,192.168.10.0/24,10.45.0.0/24"
route_add 10.250.0.2/32 wgc1 1001
route_add 192.168.10.0/24 wgc1 1001
route_add 10.45.0.0/24 wgc1 1001
vnat 10.208.0.0/24 192.168.10.0/24 wgc1 1001 10.201.0.2 0x5101 20001
vnat 10.208.1.0/24 10.45.0.0/24 wgc1 1001 10.201.0.2 0x5101 20001

# ---- MATA GRANDE (9de8a046f8985a00) index 2 ----
wg_iface wgc2 52002 10.201.0.4/31 1002 10002 "liumIl66q7nuxj6Bwzz9I9+5QN92qWcfSt4bBLgkOQI=" "10.250.0.3/32,172.16.16.0/20,192.168.10.0/24"
route_add 10.250.0.3/32 wgc2 1002
route_add 172.16.16.0/20 wgc2 1002
route_add 192.168.10.0/24 wgc2 1002
vnat 10.208.80.0/20 172.16.16.0/20 wgc2 1002 10.201.0.4 0x5102 20002
vnat 10.208.64.0/24 192.168.10.0/24 wgc2 1002 10.201.0.4 0x5102 20002
# ---- UFV-RODOANEL (4fef0f33b137a51e) index 3 ----
wg_iface wgc3 52003 10.201.0.6/31 1003 10003 "SO2lPUrPEyLSJvW8l8NEr1EC3fCBUp9OEuybcpSPmhg=" "10.201.0.7/32,10.0.0.0/23"
route_add 10.201.0.7/32 wgc3 1003
route_add 10.0.0.0/23 wgc3 1003
vnat 10.208.128.0/23 10.0.0.0/23 wgc3 1003 10.201.0.6 0x5103 20003
# ---- SANTANA (8e22b6f911073e79) index 4 ----
wg_iface wgc4 52004 10.201.0.8/31 1004 10004 "HrtMyJx0hgd6H48o1YQvf6RIFpF1ya82vC2C/K/b0EM=" "10.201.0.9/32,100.64.8.0/22"
route_add 10.201.0.9/32 wgc4 1004
route_add 100.64.8.0/22 wgc4 1004
vnat 10.208.192.0/22 100.64.8.0/22 wgc4 1004 10.201.0.8 0x5104 20004
# ---- BARRA DE SAO MIGUEL (1544b96702a23154) index 5 ----
wg_iface wgc5 52005 10.201.0.10/31 1005 10005 "ypv9nt/mJsutl4DNfSxeWkkESQXa3dfNnfBoIPz+vXU=" "10.201.0.11/32,100.65.8.0/22"
route_add 10.201.0.11/32 wgc5 1005
route_add 100.65.8.0/22 wgc5 1005
vnat 10.209.0.0/22 100.65.8.0/22 wgc5 1005 10.201.0.10 0x5105 20005
# ---- JAPARATINGA (bdd51284f07594d9) index 6 ----
wg_iface wgc6 52006 10.201.0.12/31 1006 10006 "BrQHALL9JTsiw1r3X+tD+FHouogY25BwOhv/4o4cVCQ=" "10.201.0.13/32,100.66.10.0/23,192.168.200.0/30"
route_add 10.201.0.13/32 wgc6 1006
route_add 100.66.10.0/23 wgc6 1006
route_add 192.168.200.0/30 wgc6 1006
vnat 10.209.64.0/23 100.66.10.0/23 wgc6 1006 10.201.0.12 0x5106 20006
vnat 10.209.66.0/30 192.168.200.0/30 wgc6 1006 10.201.0.12 0x5106 20006
# ---- ESCOLA PRESIDENTE DUTRA (8b1f18481e10241d) index 7 ----
wg_iface wgc7 52007 10.201.0.14/31 1007 10007 "r/21eHTknreMOfUSAkJpk2WTtwxsU0J5CT0JHOC6zw4=" "10.201.0.15/32,192.168.1.0/24"
route_add 10.201.0.15/32 wgc7 1007
route_add 192.168.1.0/24 wgc7 1007
vnat 10.209.128.0/24 192.168.1.0/24 wgc7 1007 10.201.0.14 0x5107 20007
