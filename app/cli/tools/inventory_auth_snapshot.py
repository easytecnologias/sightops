
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inventory_auth_snapshot.py (v4)

Em vez de depender de snapshot de imagem (que pode dar 404 mesmo com senha certa),
este script faz um teste LEVE autenticado em endpoints de INFO do fabricante
(Hikvision /ISAPI/System/status, Dahua /cgi-bin/magicBox.cgi, etc.) para confirmar
se a senha está correta, com no máximo 3 tentativas reais de senha por IP.

Uso típico (no Windows PowerShell):

  python tools\\inventory_auth_snapshot.py `
    --alvo 10.10.8.0/24 `
    --usuario admin `
    --senha global1234 `
    --out .\\saida\\auth_snapshot.csv `
    --csv-discovery .\\saida\\cam-discovery.csv

Saída:
  - CSV com colunas:
      ip, status, vendor_hint, model_hint,
      http_code_root, http_code_auth, auth_method, url_auth, detail

Status possíveis:
  - OFFLINE/SEM_HTTP
  - SENHA_OK
  - SENHA_ERRADA
  - ONLINE_SEM_CONFIRMAR_SENHA  (por exemplo, só retornou 404/500 nos endpoints testados)
  - ERRO (alguma exceção inesperada)
"""

import argparse
import csv
import ipaddress
import sys
from typing import Dict, List, Optional, Tuple

import requests

def _split_ipv4_host_port(value: str):
    v = (value or "").strip()
    import re as _re
    m = _re.match(r"^(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})$", v)
    if not m:
        return v, None
    try:
        return m.group(1), int(m.group(2))
    except Exception:
        return m.group(1), None

def _base_http_url(ip_or_host: str, scheme: str = "http") -> str:
    host, emb_port = _split_ipv4_host_port(ip_or_host)
    if emb_port is None:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{emb_port}"
from requests.auth import HTTPDigestAuth, HTTPBasicAuth
from requests.exceptions import RequestException


def parse_args():
    p = argparse.ArgumentParser(description="Teste leve de senha em câmeras IP (sem depender de snapshot de imagem).")
    p.add_argument("--alvo", required=True,
                   help="CIDR (10.10.8.0/24), range (10.10.8.68-10.10.8.72), lista separada por vírgula ou IP único")
    p.add_argument("--usuario", required=True, help="Usuário de autenticação HTTP")
    p.add_argument("--senha", required=True, help="Senha de autenticação HTTP")
    p.add_argument("--out", required=True, help="Caminho do CSV de saída")
    p.add_argument("--timeout", type=float, default=1.5, help="Timeout em segundos para cada request HTTP")
    p.add_argument("--csv-discovery", help="CSV de descoberta (ex.: cam-discovery.csv) pra tentar identificar vendor/model")
    return p.parse_args()


def expand_ip_range(alvo: str) -> List[str]:
    """Aceita:
       - '10.10.8.0/24'
       - '10.10.8.68-10.10.8.72'
       - '10.10.8.68,10.10.8.70,10.10.8.72'
       - '10.10.8.68'
    """
    alvo = alvo.strip()
    ips: List[str] = []

    if "," in alvo:
        for part in alvo.split(","):
            part = part.strip()
            if not part:
                continue
            ips.extend(expand_ip_range(part))
        return ips

    if "/" in alvo:
        net = ipaddress.ip_network(alvo, strict=False)
        return [str(ip) for ip in net.hosts()]

    if "-" in alvo:
        start_str, end_str = [x.strip() for x in alvo.split("-", 1)]
        start_ip = ipaddress.IPv4Address(start_str)
        end_ip = ipaddress.IPv4Address(end_str)
        if int(end_ip) < int(start_ip):
            start_ip, end_ip = end_ip, start_ip
        return [str(ipaddress.IPv4Address(i)) for i in range(int(start_ip), int(end_ip) + 1)]

    # IP único
    return [alvo]


def load_discovery_csv(path: Optional[str]) -> Dict[str, Dict[str, str]]:
    """Lê um cam-discovery.csv (ou similar) e devolve dict[ip] -> {vendor_hint, model_hint, ...}"""
    if not path:
        return {}

    data: Dict[str, Dict[str, str]] = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ip = (row.get("ip") or row.get("IP") or "").strip()
                if not ip:
                    continue

                vendor = (
                    row.get("vendor")
                    or row.get("brand")
                    or row.get("fabricante")
                    or row.get("fabricante_detectado")
                    or ""
                )
                model = (
                    row.get("model")
                    or row.get("modelo")
                    or row.get("model_guess")
                    or ""
                )

                data[ip] = {
                    "vendor_hint": vendor.strip(),
                    "model_hint": model.strip(),
                }
    except Exception as e:
        print(f"[WARN] Falha ao ler CSV de discovery '{path}': {e}", file=sys.stderr)
    return data


def guess_vendor(vendor_hint: str, model_hint: str) -> str:
    """Tenta adivinhar o fabricante em cima das strings do discovery."""
    text = (vendor_hint + " " + model_hint).lower()

    if any(x in text for x in ["hikvision", "hilook", "hik-"]):
        return "hikvision"
    if "intelbras" in text and "multi" not in text:
        # muitos Intelbras são dahua OEM
        if any(x in text for x in ["vip-", "vhd", "mibo", "multi"]):
            return "intelbras"
        return "intelbras/dahua"
    if any(x in text for x in ["dahua", "oem"]):
        return "dahua"
    if any(x in text for x in ["axis"]):
        return "axis"
    if any(x in text for x in ["uniview", "unv"]):
        return "uniview"
    return ""


def build_auth_endpoints(ip: str, vendor_detected: str) -> List[str]:
    """
    Lista de endpoints leves que exigem autenticação e que, se retornarem 200,
    indicam que a senha está correta.
    """
    base_http = f"http://{ip}"
    endpoints: List[str] = []

    # Hikvision / Hilook: ISAPI
    hik_paths = [
        "/ISAPI/System/status",
        "/ISAPI/System/deviceInfo",
        "/ISAPI/ContentMgmt/status",
    ]

    # Dahua / Intelbras OEM
    dahua_paths = [
        "/cgi-bin/magicBox.cgi?action=getMachineName",
        "/cgi-bin/configManager.cgi?action=getConfig&name=General",
        "/cgi-bin/magicBox.cgi?action=getSystemInfo",
    ]

    # Intelbras próprios (alguns)
    intelbras_extra = [
        "/cgi-bin/system.cgi?cmd=getdevinfo",
    ]

    # ONVIF genéricos (muitos devices aceitam sem snapshot)
    generic_paths = [
        "/onvif/device_service",
    ]

    v = vendor_detected.lower()

    if "hik" in v or "hilook" in v:
        for p in hik_paths + generic_paths:
            endpoints.append(base_http + p)
    elif "dahua" in v or "oem" in v:
        for p in dahua_paths + generic_paths:
            endpoints.append(base_http + p)
    elif "intelbras" in v:
        for p in (dahua_paths + intelbras_extra + generic_paths):
            endpoints.append(base_http + p)
    else:
        # vendor desconhecido: tenta um mix
        for p in (hik_paths + dahua_paths + generic_paths):
            endpoints.append(base_http + p)

    # garante que não haja duplicados preservando a ordem
    seen = set()
    unique_endpoints = []
    for url in endpoints:
        if url not in seen:
            seen.add(url)
            unique_endpoints.append(url)
    return unique_endpoints


def test_ip_auth(
    ip: str,
    user: str,
    password: str,
    vendor_hint: str,
    model_hint: str,
    timeout: float = 1.5,
) -> Tuple[str, Dict[str, str]]:
    """
    Faz:
      1) GET na raiz sem auth → ver se está online (código HTTP)
      2) Tenta autenticar em alguns endpoints leves (Hik/Dahua/Intelbras/Genérico),
         usando primeiro Digest e depois Basic, até 3 tentativas de senha no total.

    Retorna:
      status, extra_info_dict
    """
    info: Dict[str, str] = {
        "ip": ip,
        "vendor_hint": vendor_hint,
        "model_hint": model_hint,
        "http_code_root": "",
        "http_code_auth": "",
        "auth_method": "",
        "url_auth": "",
        "detail": "",
    }

    base_http = f"http://{ip}"
    # 1) Teste da raiz sem auth
    try:
        r = requests.get(base_http, timeout=timeout)
        info["http_code_root"] = str(r.status_code)
    except RequestException as e:
        info["detail"] = f"Erro ao acessar raiz: {e}"
        return "OFFLINE/SEM_HTTP", info

    # se código raiz é 4xx/5xx, ainda pode ser que haja endpoints de autenticação
    # mas sabemos que HTTP responde.

    # 2) Testes autenticados
    vendor_detected = guess_vendor(vendor_hint, model_hint)
    endpoints = build_auth_endpoints(ip, vendor_detected or vendor_hint)

    if not endpoints:
        info["detail"] = "Nenhum endpoint de autenticação definido"
        return "ONLINE_SEM_CONFIRMAR_SENHA", info

    senha_errada_clara = False
    alguma_resposta = False
    tentativas_senha = 0

    for url in endpoints:
        if tentativas_senha >= 3:
            break

        for method_name, auth_obj in (
            ("digest", HTTPDigestAuth(user, password)),
            ("basic", HTTPBasicAuth(user, password)),
        ):
            if tentativas_senha >= 3:
                break

            tentativas_senha += 1
            try:
                r = requests.get(url, auth=auth_obj, timeout=timeout)
                alguma_resposta = True
                info["http_code_auth"] = str(r.status_code)
                info["auth_method"] = method_name
                info["url_auth"] = url

                if r.status_code == 200:
                    info["detail"] = f"HTTP 200 em {url} via {method_name} (senha aceita)."
                    return "SENHA_OK", info
                elif r.status_code in (401, 403):
                    # senha errada detectada explicitamente
                    senha_errada_clara = True
                    info["detail"] = f"HTTP {r.status_code} em {url} via {method_name} (senha recusada)."
                    # já temos certeza que essa senha não funciona em pelo menos 1 endpoint
                    return "SENHA_ERRADA", info
                else:
                    # 404, 500, etc. Não confirma nem nega a senha.
                    # Apenas registra e segue tentando outro endpoint.
                    info["detail"] = f"HTTP {r.status_code} em {url} via {method_name} (sem confirmação de senha)."
            except RequestException as e:
                info["detail"] = f"Erro em {url} via {method_name}: {e}"

    # Se chegamos aqui:
    if senha_errada_clara:
        return "SENHA_ERRADA", info
    if not alguma_resposta:
        return "OFFLINE/SEM_HTTP", info

    # Responderam HTTP, mas nunca confirmaram a senha com 200
    return "ONLINE_SEM_CONFIRMAR_SENHA", info


def main():
    args = parse_args()

    ips = expand_ip_range(args.alvo)
    print(f"[INFO] IPs a testar: {len(ips)}")
    print(f"[INFO] Usuário: {args.usuario}")
    print(f"[INFO] Saída CSV: {args.out}")
    if args.csv_discovery:
        print(f"[INFO] CSV discovery: {args.csv_discovery}")

    discovery_map = load_discovery_csv(args.csv_discovery)

    rows_out: List[Dict[str, str]] = []
    resumo_counts = {
        "SENHA_OK": 0,
        "SENHA_ERRADA": 0,
        "OFFLINE/SEM_HTTP": 0,
        "ONLINE_SEM_CONFIRMAR_SENHA": 0,
        "ERRO": 0,
    }

    for ip in ips:
        print(f"[TEST] Testando {ip}...")
        hints = discovery_map.get(ip, {})
        vendor_hint = hints.get("vendor_hint", "")
        model_hint = hints.get("model_hint", "")

        try:
            status, info = test_ip_auth(
                ip=ip,
                user=args.usuario,
                password=args.senha,
                vendor_hint=vendor_hint,
                model_hint=model_hint,
                timeout=args.timeout,
            )
        except Exception as e:
            status = "ERRO"
            info = {
                "ip": ip,
                "vendor_hint": vendor_hint,
                "model_hint": model_hint,
                "http_code_root": "",
                "http_code_auth": "",
                "auth_method": "",
                "url_auth": "",
                "detail": f"Exceção inesperada: {e}",
            }

        resumo_counts[status] = resumo_counts.get(status, 0) + 1
        info["status"] = status
        rows_out.append(info)

        print(f"   -> {status} ({info.get('detail', '')})")

    # Escreve CSV
    fieldnames = [
        "ip",
        "status",
        "vendor_hint",
        "model_hint",
        "http_code_root",
        "http_code_auth",
        "auth_method",
        "url_auth",
        "detail",
    ]

    try:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows_out:
                writer.writerow(row)
        print(f"[INFO] Resultado salvo em: {args.out}")
    except Exception as e:
        print(f"[ERRO] Falha ao gravar CSV de saída '{args.out}': {e}", file=sys.stderr)

    print("\n[RESUMO]")
    total = sum(resumo_counts.values())
    print(f"  Total de IPs testados        : {total}")
    print(f"  SENHA OK                     : {resumo_counts['SENHA_OK']}")
    print(f"  SENHA ERRADA (401/403)       : {resumo_counts['SENHA_ERRADA']}")
    print(f"  Offline / sem HTTP           : {resumo_counts['OFFLINE/SEM_HTTP']}")
    print(f"  Online, senha NÃO confirmada : {resumo_counts['ONLINE_SEM_CONFIRMAR_SENHA']}")
    print(f"  Erro inesperado              : {resumo_counts['ERRO']}")

    print("\n[INFO] Para cada IP foram feitas, no máximo, 3 tentativas reais de senha (endpoints leves).")


if __name__ == "__main__":
    main()
