#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
discover_cameras.py — Descoberta universal de dispositivos de vídeo (estilo SADP/IP Utility, multi-fabricante)

Camadas de descoberta:
1) ONVIF WS-Discovery (multicast UDP)   → descobre câmeras/NVR ONVIF, mesmo com portas HTTP/RTSP alteradas
2) SSDP/UPnP (M-SEARCH)                 → descobre dispositivos que se anunciam na rede (IP Camera, NVR, etc.)
3) Scanner TCP (portas típicas)         → fallback baseado em portas + HTTP + MAC

Saída: CSV único com o melhor que foi encontrado por IP.
"""

import argparse
import csv
import ipaddress
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    requests = None

# ---------------------- Configuração básica ----------------------

# Portas TCP típicas de dispositivos de vídeo e telefonia
DEFAULT_PORTS = [
    80, 81, 88, 8080, 8000,      # HTTP / web
    554,                         # RTSP
    37777, 8899,                 # Dahua / OEM
    5060, 5061                   # SIP (telefone IP / ramal)
]

# Palavras-chave para detectar fabricante a partir de título HTML / corpo
BRAND_KEYWORDS = {
    "hikvision": "Hikvision",
    "hilook": "Hikvision/HiLook",
    "dahua": "Dahua",
    "intelbras": "Intelbras",
    "amcrest": "Amcrest",
    "axis": "Axis",
    "bosch": "Bosch",
    "ip camera": "Genérico IP-Camera",
    "ipcam": "Genérico IP-Camera",
    "onvif": "ONVIF Genérico",
}

print_lock = threading.Lock()


def log(msg: str) -> None:
    with print_lock:
        print(msg, flush=True)


@dataclass
class DiscoveredDevice:
    ip: str
    mac: str = ""
    http_port: Optional[int] = None
    rtsp_port: Optional[int] = None
    open_ports: str = ""

    fabricante_guess: str = ""
    modelo_guess: str = ""
    device_type: str = ""          # camera / nvr / dvr / ip_phone / unknown

    is_onvif: bool = False
    onvif_xaddrs: str = ""
    onvif_scopes: str = ""

    ssdp_server: str = ""
    ssdp_location: str = ""

    brand_source: str = ""
    model_source: str = ""
    http_title: str = ""
    last_error: str = ""


# ---------------------- Parsing de alvo ----------------------


def parse_targets(alvo: str) -> List[str]:
    """
    Suporta:
    - CIDR: 10.10.10.0/24
    - Range: 10.10.9.20-10.10.9.107
    - Lista: 10.10.9.20,10.10.9.21
    - IP único
    """
    alvo = alvo.strip()
    ips: List[str] = []

    if "," in alvo:
        for parte in [p.strip() for p in alvo.split(",") if p.strip()]:
            ips.extend(parse_targets(parte))
        return sorted(set(ips))

    if "/" in alvo:
        net = ipaddress.ip_network(alvo, strict=False)
        return [str(ip) for ip in net.hosts()]

    if "-" in alvo:
        base, end = alvo.split("-", 1)
        base_ip = ipaddress.ip_address(base.strip())
        end_ip = ipaddress.ip_address(end.strip())
        if int(end_ip) < int(base_ip):
            raise ValueError("Range inválido (fim < início)")
        return [str(ipaddress.ip_address(i)) for i in range(int(base_ip), int(end_ip) + 1)]

    ipaddress.ip_address(alvo)  # valida
    return [alvo]


# ---------------------- Utilitários de rede ----------------------


def tcp_connect(ip: str, port: int, timeout: float = 1.0) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def get_mac_via_arp(ip: str) -> str:
    ip = ip.strip()
    try:
        if sys.platform.startswith("win"):
            out = subprocess.check_output(["arp", "-a", ip], encoding="utf-8", errors="ignore")
            for line in out.splitlines():
                if ip in line:
                    parts = line.split()
                    for p in parts:
                        if "-" in p and len(p) >= 17:
                            return p.replace("-", ":").lower()
        else:
            try:
                out = subprocess.check_output(["ip", "neigh"], encoding="utf-8", errors="ignore")
            except Exception:
                out = subprocess.check_output(["arp", "-n"], encoding="utf-8", errors="ignore")
            for line in out.splitlines():
                if ip in line:
                    parts = line.split()
                    for p in parts:
                        if ":" in p and len(p) >= 17:
                            return p.lower()
    except Exception:
        pass
    return ""


def guess_brand_from_mac(mac: str) -> Optional[str]:
    if not mac:
        return None
    prefix = mac.upper().replace("-", ":").split(":")[:3]
    if len(prefix) < 3:
        return None
    oui = ":".join(prefix)
    OUI_MAP = {
        "E0:CA:3C": "Intelbras",
        "D4:AE:52": "Intelbras",
        "BC:51:FE": "Hikvision",
        "3C:EF:8C": "Dahua",
    }
    return OUI_MAP.get(oui)


# ---------------------- Fingerprint HTTP ----------------------


def get_http_fingerprint(ip: str, port: int, timeout: float = 1.0) -> Tuple[str, str, str]:
    """
    Retorna (fabricante_guess, modelo_guess, http_title).
    Usa requests se disponível.
    """
    if requests is None:
        return "", "", ""

    url = f"http://{ip}:{port}/"
    fabricante = ""
    modelo = ""
    title = ""

    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
        text = resp.text or ""
        lower_all = text.lower()

        # título
        import re
        m = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            title = m.group(1).strip()

        lower_all = (title + " " + lower_all).lower()

        for kw, brand in BRAND_KEYWORDS.items():
            if kw in lower_all:
                fabricante = brand
                break

        m2 = re.search(r"(vip[-\s]?\w+|ipc[-\s]?\w+|ip camera \w+|v\d{3,4})", lower_all)
        if m2:
            modelo = m2.group(1).strip()

    except Exception:
        pass

    return fabricante, modelo, title


# ---------------------- Classificação de tipo ----------------------


def classify_device(fabricante: str, modelo: str, title: str) -> str:
    txt = (fabricante + " " + modelo + " " + (title or "")).lower()

    # Telefone IP / VoIP
    if "ip phone" in txt or "voip" in txt or "ramal" in txt or "telefone" in txt or "v3001" in txt:
        return "ip_phone"

    if "nvr" in txt:
        return "nvr"
    if "dvr" in txt:
        return "dvr"
    if "ip camera" in txt or "ipc" in txt or "vip" in txt or "camera" in txt:
        return "camera"

    return "unknown"


def refine_device(dev: DiscoveredDevice) -> None:
    """
    Ajustes finos pós-scan TCP:
    - telefone IP por portas SIP
    - padrões típicos Hik/HiLook e Dahua/OEM
    - leitores faciais OEM por padrão de porta
    - switches smart Hikvision por padrão de porta
    - qualquer coisa com RTSP vira 'dispositivo de vídeo'
    """
    txt = (dev.http_title or "").lower()
    ports = set(int(p) for p in dev.open_ports.split(",") if p)

    # Telefone IP (porta SIP, sem RTSP)
    if (5060 in ports or 5061 in ports) and 554 not in ports:
        if dev.device_type in ("", "unknown", None):
            dev.device_type = "ip_phone"
        if not dev.fabricante_guess and "intelbras" in txt:
            dev.fabricante_guess = "Intelbras"
            dev.brand_source = dev.brand_source or "http_title"

    # Padrão Hik/HiLook: 80 + 8000 + 554 (câmera / speed dome)
    if {80, 8000, 554}.issubset(ports):
        if not dev.fabricante_guess:
            dev.fabricante_guess = "Hikvision/HiLook"
            dev.brand_source = dev.brand_source or "ports_pattern"
        if dev.device_type in ("", "unknown", None):
            dev.device_type = "camera"
        dev.is_onvif = True

    # Dahua / Intelbras OEM: 37777 + 554 (câmera IP OEM)
    if 37777 in ports and 554 in ports:
        if not dev.fabricante_guess:
            dev.fabricante_guess = "Dahua/OEM"
            dev.brand_source = dev.brand_source or "ports_pattern"
        if dev.device_type in ("", "unknown", None):
            dev.device_type = "camera"

    # Leitor facial Dahua/Intelbras OEM (porta 37777 pura, sem HTTP/RTSP)
    if dev.open_ports == "37777":
        if not dev.fabricante_guess:
            dev.fabricante_guess = "Dahua/OEM"
        dev.brand_source = dev.brand_source or "ports_pattern_facial"
        dev.device_type = "facial_reader"

    # Switch smart Hikvision (heurística local para portas 80 ou 8000)
    if dev.device_type in ("", "unknown", None) and dev.open_ports in ("80", "8000"):
        dev.device_type = "switch"
        if not dev.fabricante_guess:
            dev.fabricante_guess = "Hikvision (switch)"
            dev.brand_source = dev.brand_source or "ports_pattern_switch"

    # Se tem RTSP, é dispositivo de vídeo (câmera/NVR)
    if 554 in ports and dev.device_type in ("", "unknown", None):
        dev.device_type = "camera"


# ---------------------- ONVIF WS-Discovery ----------------------


def discover_onvif(timeout: float = 3.0) -> Dict[str, Dict[str, str]]:
    """
    Envia um WS-Discovery Probe para multicast ONVIF e coleta respostas.
    Retorna dict: ip -> { 'manufacturer': ..., 'model': ..., 'xaddrs': ..., 'scopes': ... }
    """
    log("[INFO] Descobrindo dispositivos ONVIF via WS-Discovery...")
    group = ("239.255.255.250", 3702)
    message = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
    xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
    xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
    xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:12345678-1234-1234-1234-123456789abc</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>
"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    ttl = 2
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    devices: Dict[str, Dict[str, str]] = {}

    try:
        sock.sendto(message.encode("utf-8"), group)
    except Exception as e:
        log(f"[WARN] Falha ao enviar Probe ONVIF: {e}")
        sock.close()
        return devices

    start = time.time()
    while time.time() - start < timeout:
        try:
            data, addr = sock.recvfrom(8192)
        except socket.timeout:
            break
        except Exception as e:
            log(f"[WARN] Erro ao receber resposta ONVIF: {e}")
            break

        ip = addr[0]
        text = data.decode("utf-8", errors="ignore")
        lower = text.lower()

        # XAddrs
        xaddrs = ""
        import re
        m = re.search(r"<.*?xaddrs.*?>(.*?)</", text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            xaddrs = m.group(1).strip()

        # Scopes (contém manufacturer/model às vezes)
        scopes = ""
        m2 = re.findall(r"<.*?scopes.*?>(.*?)</", text, flags=re.IGNORECASE | re.DOTALL)
        if m2:
            scopes = " ".join(s.strip() for s in m2)

        manufacturer = ""
        model = ""

        # tentar encontrar via escopos
        if "onvif://www.onvif.org/name/" in lower or "onvif://www.onvif.org" in lower:
            # Não fazemos parse fino aqui; deixamos nos scopes completos.
            pass

        if ip not in devices:
            devices[ip] = {
                "manufacturer": manufacturer,
                "model": model,
                "xaddrs": xaddrs,
                "scopes": scopes,
            }

    sock.close()
    log(f"[INFO] ONVIF: encontrados {len(devices)} IPs respondendo Probe.")
    return devices


# ---------------------- SSDP / UPnP (M-SEARCH) ----------------------


def discover_ssdp(timeout: float = 3.0) -> Dict[str, Dict[str, str]]:
    """
    Envia M-SEARCH SSDP e coleta respostas.
    Retorna dict: ip -> { 'server': ..., 'location': ... }
    """
    log("[INFO] Descobrindo dispositivos via SSDP/UPnP...")
    group = ("239.255.255.250", 1900)
    message = "\r\n".join([
        "M-SEARCH * HTTP/1.1",
        f"HOST: {group[0]}:{group[1]}",
        "MAN: \"ssdp:discover\"",
        "MX: 2",
        "ST: ssdp:all",
        "",
        "",
    ])

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    ttl = 2
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    devices: Dict[str, Dict[str, str]] = {}

    try:
        sock.sendto(message.encode("utf-8"), group)
    except Exception as e:
        log(f"[WARN] Falha ao enviar M-SEARCH SSDP: {e}")
        sock.close()
        return devices

    start = time.time()
    while time.time() - start < timeout:
        try:
            data, addr = sock.recvfrom(8192)
        except socket.timeout:
            break
        except Exception as e:
            log(f"[WARN] Erro ao receber resposta SSDP: {e}")
            break

        ip = addr[0]
        text = data.decode("utf-8", errors="ignore")
        lower = text.lower()

        server = ""
        location = ""

        for line in text.splitlines():
            if line.lower().startswith("server:"):
                server = line.split(":", 1)[1].strip()
            if line.lower().startswith("location:"):
                location = line.split(":", 1)[1].strip()

        if ip not in devices:
            devices[ip] = {
                "server": server,
                "location": location,
            }

    sock.close()
    log(f"[INFO] SSDP: encontrados {len(devices)} IPs respondendo M-SEARCH.")
    return devices


# ---------------------- Scanner TCP por IP ----------------------


def scan_ip_tcp(ip: str, ports: List[int], timeout: float = 1.0) -> Optional[DiscoveredDevice]:
    dev = DiscoveredDevice(ip=ip)
    open_ports: List[int] = []

    for p in ports:
        if tcp_connect(ip, p, timeout=timeout):
            open_ports.append(p)

    if not open_ports:
        return None

    dev.open_ports = ",".join(str(p) for p in open_ports)

    for hp in [80, 81, 88, 8000, 8080]:
        if hp in open_ports:
            dev.http_port = hp
            break

    if 554 in open_ports:
        dev.rtsp_port = 554

    dev.mac = get_mac_via_arp(ip) or ""

    mac_brand = guess_brand_from_mac(dev.mac)
    if mac_brand:
        dev.fabricante_guess = mac_brand
        dev.brand_source = "mac_oui"

    if dev.http_port is not None:
        fab_http, modelo_http, title = get_http_fingerprint(ip, dev.http_port, timeout=timeout)
        dev.http_title = title

        if fab_http and not dev.fabricante_guess:
            dev.fabricante_guess = fab_http
            dev.brand_source = "http_keyword"

        if modelo_http and not dev.modelo_guess:
            dev.modelo_guess = modelo_http
            dev.model_source = "http_regex"

    dev.device_type = classify_device(dev.fabricante_guess or "", dev.modelo_guess or "", dev.http_title or "")
    refine_device(dev)

    return dev


# ---------------------- Merge das fontes ----------------------


def merge_devices(
    ips: List[str],
    onvif_map: Dict[str, Dict[str, str]],
    ssdp_map: Dict[str, Dict[str, str]],
    tcp_map: Dict[str, DiscoveredDevice],
) -> List[DiscoveredDevice]:
    merged: Dict[str, DiscoveredDevice] = {}

    for ip in ips:
        merged[ip] = DiscoveredDevice(ip=ip)

    # ONVIF
    for ip, info in onvif_map.items():
        dev = merged.setdefault(ip, DiscoveredDevice(ip=ip))
        dev.is_onvif = True
        dev.onvif_xaddrs = info.get("xaddrs", "")
        dev.onvif_scopes = info.get("scopes", "")
        # fabricante/modelo podem vir de scopes (futuro: parsear melhor)

    # SSDP
    for ip, info in ssdp_map.items():
        dev = merged.setdefault(ip, DiscoveredDevice(ip=ip))
        dev.ssdp_server = info.get("server", "")
        dev.ssdp_location = info.get("location", "")

    # TCP/fingerprint
    for ip, tdev in tcp_map.items():
        dev = merged.setdefault(ip, DiscoveredDevice(ip=ip))
        for field in asdict(tdev):
            val = getattr(tdev, field)
            if not getattr(dev, field):
                setattr(dev, field, val)

    # classificação final: se ONVIF e device_type vazio → marcar como camera
    for dev in merged.values():
        if dev.is_onvif and dev.device_type in ("", "unknown", None):
            dev.device_type = "camera"

    return list(merged.values())


# ---------------------- CSV ----------------------


def write_csv(devices: List[DiscoveredDevice], out_path: str) -> None:
    fieldnames = [
        "ip",
        "mac",
        "http_port",
        "rtsp_port",
        "open_ports",
        "fabricante_guess",
        "modelo_guess",
        "device_type",
        "is_onvif",
        "onvif_xaddrs",
        "onvif_scopes",
        "ssdp_server",
        "ssdp_location",
        "brand_source",
        "model_source",
        "http_title",
        "last_error",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for dev in sorted(devices, key=lambda d: d.ip):
            w.writerow(asdict(dev))


# ---------------------- main() ----------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Descoberta universal de dispositivos de vídeo (ONVIF + SSDP + TCP)."
    )
    parser.add_argument(
        "--alvo",
        required=True,
        help="CIDR, range (A-B), lista separada por vírgula ou IP único",
    )
    parser.add_argument(
        "--out",
        default=r".\saida\cam-discovery.csv",
        help="CSV de saída (padrão: .\\saida\\cam-discovery.csv)",
    )
    parser.add_argument(
        "--ports",
        default=",".join(str(p) for p in DEFAULT_PORTS),
        help=f"Portas TCP a testar (padrão: {DEFAULT_PORTS})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="Timeout por conexão e por resposta (padrão: 1.0s)",
    )
    parser.add_argument(
        "--max-threads",
        type=int,
        default=64,
        help="Máximo de threads no scan TCP (padrão: 64)",
    )
    args = parser.parse_args(argv)

    try:
        ips = parse_targets(args.alvo)
    except Exception as e:
        log(f"[ERRO] Alvo inválido: {e}")
        return 1

    ports: List[int] = []
    for p in args.ports.split(","):
        p = p.strip()
        if not p:
            continue
        try:
            ports.append(int(p))
        except ValueError:
            log(f"[WARN] Porta ignorada (não numérica): {p!r}")
    if not ports:
        ports = DEFAULT_PORTS

    log(f"[INFO] Alvo expandido: {len(ips)} IPs")
    log(f"[INFO] Portas TCP: {ports}")
    log(f"[INFO] Timeout: {args.timeout}s | Threads: {args.max_threads}")
    log(f"[INFO] Saída: {args.out}")

    # 1) ONVIF
    onvif_map = discover_onvif(timeout=args.timeout * 3)

    # 2) SSDP
    ssdp_map = discover_ssdp(timeout=args.timeout * 3)

    # 3) TCP scan
    log("[INFO] Iniciando scan TCP/fingerprint...")
    tcp_map: Dict[str, DiscoveredDevice] = {}
    with ThreadPoolExecutor(max_workers=args.max_threads) as executor:
        futures = {executor.submit(scan_ip_tcp, ip, ports, args.timeout): ip for ip in ips}
        for fut in as_completed(futures):
            ip = futures[fut]
            try:
                dev = fut.result()
                if dev is not None:
                    tcp_map[ip] = dev
                    log(f"[OK] {ip} -> {dev.fabricante_guess or 'desconhecido'} "
                        f"(ports: {dev.open_ports})")
            except Exception as e:
                log(f"[ERRO] Falha ao escanear {ip}: {e}")

    merged = merge_devices(ips, onvif_map, ssdp_map, tcp_map)

    # remover IPs completamente vazios
    final_devices = [
        d for d in merged
        if d.open_ports or d.is_onvif or d.ssdp_server or d.ssdp_location
    ]

    if final_devices:
        import os
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        write_csv(final_devices, args.out)
        log(f"[INFO] Descoberta concluída. {len(final_devices)} dispositivos gravados em {args.out}")
    else:
        log("[INFO] Nenhum dispositivo relevante encontrado.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
