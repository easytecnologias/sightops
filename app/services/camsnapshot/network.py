
# camsnapshot/network.py
import ipaddress
from typing import List
import re, socket, subprocess

RANGE_RE = re.compile(r"^(\d+\.\d+\.\d+\.\d+)\s*-\s*(\d+\.\d+\.\d+\.\d+)$")

def _hosts_from_cidr(cidr: str) -> List[str]:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        return [str(ip) for ip in net.hosts()]
    except Exception:
        return []

def _hosts_from_range(start_ip: str, end_ip: str) -> List[str]:
    try:
        start = ipaddress.IPv4Address(start_ip)
        end = ipaddress.IPv4Address(end_ip)
        if int(end) < int(start):
            return []
        return [str(ipaddress.IPv4Address(i)) for i in range(int(start), int(end) + 1)]
    except Exception:
        return []

def _hosts_from_list(s: str) -> List[str]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    hosts: List[str] = []
    for p in parts:
        if "/" in p:  # CIDR
            hosts.extend(_hosts_from_cidr(p))
            continue
        m = RANGE_RE.match(p)  # Range
        if m:
            hosts.extend(_hosts_from_range(m.group(1), m.group(2)))
            continue
        # Single IP
        try:
            ip = ipaddress.ip_address(p)
            hosts.append(str(ip))
        except Exception:
            continue
    # Remover duplicatas preservando ordem
    seen = set()
    ordered = []
    for h in hosts:
        if h not in seen:
            seen.add(h)
            ordered.append(h)
    return ordered

def expand_network(alvo: str) -> List[str]:
    """
    Aceita:
      - CIDR: 10.10.9.16/28
      - Range: 10.10.9.20-10.10.9.30
      - Lista: 10.10.9.20,10.10.9.22,10.10.9.25
      - IP único: 10.10.9.20
    """
    alvo = (alvo or "").strip()
    if not alvo:
        return []
    if "," in alvo or RANGE_RE.match(alvo):
        return _hosts_from_list(alvo)
    if "/" in alvo:
        return _hosts_from_cidr(alvo)
    try:
        ip = ipaddress.ip_address(alvo)
        return [str(ip)]
    except Exception:
        return []

# Utilidades de rede
def tcp_check(ip, port=80, timeout=1.2):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def get_mac_arp(ip):
    """Resolve MAC via ARP (Windows)."""
    try:
        subprocess.run(["ping", "-n", "1", "-w", "300", ip],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        res = subprocess.run(["arp", "-a", ip], capture_output=True, text=True, encoding="utf-8", errors="ignore")
        out = res.stdout or ""
        m = re.search(r"([0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}", out)
        if m:
            return m.group(0).lower().replace('-', ':')
    except Exception:
        pass
    return None
