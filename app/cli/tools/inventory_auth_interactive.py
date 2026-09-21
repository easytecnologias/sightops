#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
inventory_auth_interactive.py — Pré-checagem interativa de senha para câmeras/gravadores

Objetivo:
- Evitar travar equipamentos por senha errada.
- Testar a combinação usuário/senha em cada IP APENAS UMA VEZ.
- Descobrir quem aceita a senha, quem está com senha errada e quem está offline.
- No final, mostrar:
    - comandos prontos para rodar o inventory_scan.py apenas nos IPs com senha OK;
    - comandos sugeridos para os IPs com senha errada, pedindo senha nova interativamente.

OBS: Este script NÃO executa o inventário. Ele é um passo ANTES do inventory_scan.py,
para você saber onde sua senha funciona com segurança.

Uso típico:

    python tools\inventory_auth_interactive.py ^
      --alvo 10.10.9.20-10.10.9.107 ^
      --usuario admin ^
      --senha global1234 ^
      --out .\saida\auth_check.csv

Depois, use os comandos sugeridos no final para rodar o inventory_scan.py apenas
nos IPs com senha correta ou corrigida.
"""

import argparse
import csv
import ipaddress
import socket
from dataclasses import dataclass, asdict
from typing import List, Optional

try:
    import requests
except ImportError:
    requests = None


@dataclass
class AuthResult:
    ip: str
    status: str          # ok / wrong_password / offline / error / no_http
    http_status: str = ""
    detail: str = ""


def log(msg: str) -> None:
    print(msg, flush=True)


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


def check_auth_http(ip: str, usuario: str, senha: str, timeout: float = 1.5) -> AuthResult:
    """
    Faz UMA tentativa de autenticação HTTP em um endpoint que, na maioria dos casos,
    exige senha de verdade.

    Estratégia em 2 passos por IP:
    1) Primeiro GET em "/" SEM autenticação, apenas para:
       - confirmar se há HTTP respondendo;
       - inspecionar o header "Server" para tentar adivinhar fabricante.

    2) Depois, UM GET autenticado em um endpoint "mais protegido":
       - se parecer Hikvision: /ISAPI/System/deviceInfo
       - se parecer Dahua/Intelbras OEM: /cgi-bin/magicBox.cgi?action=getSystemInfo
       - caso contrário: "/" mesmo (fallback)

    Interpretação:
    - 401/403 nesse endpoint protegido => wrong_password
    - 200/301/302/404/etc. => ok (senha aceita ou endpoint público; pelo menos não foi rejeitada)
    - timeout / conexão recusada => offline
    """
    if requests is None:
        return AuthResult(ip=ip, status="no_http", detail="biblioteca 'requests' não instalada")

    base_url = f"http://{ip}"
    server_header = ""
    try:
        # Passo 1: checa se há HTTP vivo e tenta detectar fabricante pelo header
        r0 = requests.get(f"{base_url}/", timeout=timeout, allow_redirects=True)
        server_header = r0.headers.get("Server", "") or ""
    except requests.RequestException as e:
        # Se nem a página inicial responde, consideramos offline
        return AuthResult(ip=ip, status="offline", detail=str(e))

    # Decide endpoint de teste de senha baseado em pistas do Server
    server_lower = server_header.lower()
    if "hikvision" in server_lower:
        path = "/ISAPI/System/deviceInfo"
    elif "dahua" in server_lower or "netsurveillance" in server_lower or "intelbras" in server_lower:
        path = "/cgi-bin/magicBox.cgi?action=getSystemInfo"
    else:
        # Fallback: usa a raiz, como na versão anterior
        path = "/"

    try:
        resp = requests.get(f"{base_url}{path}", auth=(usuario, senha), timeout=timeout, allow_redirects=True)
        status = resp.status_code

        if status in (401, 403):
            return AuthResult(ip=ip, status="wrong_password", http_status=str(status), detail=f"HTTP auth falhou ({status})")
        else:
            # 200, 3xx, 404 etc: não houve rejeição explícita da senha
            return AuthResult(ip=ip, status="ok", http_status=str(status), detail=f"HTTP {status} em {path}")
    except requests.RequestException as e:
        # Se a página protegida der erro, mas a raiz respondeu, marcamos como erro genérico
        return AuthResult(ip=ip, status="error", detail=str(e))


def write_csv(results: List[AuthResult], out_path: str) -> None:
    fieldnames = list(AuthResult.__dataclass_fields__.keys())
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow(asdict(r))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pré-checagem interativa de senha para câmeras/gravadores.")
    parser.add_argument("--alvo", required=True, help="CIDR, range (A-B), lista separada por vírgula ou IP único")
    parser.add_argument("--usuario", required=True, help="Usuário para autenticação HTTP (ex.: admin)")
    parser.add_argument("--senha", required=True, help="Senha para autenticação HTTP")
    parser.add_argument("--timeout", type=float, default=1.5, help="Timeout por requisição HTTP (padrão: 1.5s)")
    parser.add_argument("--out", default=r".\\saida\\auth_check.csv", help="CSV de saída com o resultado do teste de senha")

    args = parser.parse_args(argv)

    try:
        ips = parse_targets(args.alvo)
    except Exception as e:
        log(f"[ERRO] Alvo inválido: {e}")
        return 1

    if not ips:
        log("[ERRO] Nenhum IP válido no alvo.")
        return 1

    if requests is None:
        log("[ERRO] Este script exige a biblioteca 'requests'. Instale com: pip install requests")
        return 1

    log(f"[INFO] IPs a testar: {len(ips)}")
    log(f"[INFO] Usuário: {args.usuario}")
    log(f"[INFO] Saída CSV: {args.out}")

    results: List[AuthResult] = []
    ok_ips: List[str] = []
    wrong_ips: List[str] = []
    offline_ips: List[str] = []

    for ip in ips:
        log(f"[TEST] Testando {ip}...")
        res = check_auth_http(ip, args.usuario, args.senha, timeout=args.timeout)
        results.append(res)

        if res.status == "ok":
            ok_ips.append(ip)
            log(f"   -> OK (HTTP {res.http_status or res.detail})")
        elif res.status == "wrong_password":
            wrong_ips.append(ip)
            log(f"   -> SENHA ERRADA (HTTP {res.http_status})")
        elif res.status == "offline":
            offline_ips.append(ip)
            log(f"   -> OFFLINE/SEM RESPOSTA ({res.detail})")
        else:
            log(f"   -> {res.status} ({res.detail})")

    # grava CSV com diagnóstico
    import os
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    write_csv(results, args.out)
    log(f"[INFO] Resultado salvo em: {args.out}")

    # resumo
    log("\n[RESUMO]")
    log(f"  Total de IPs testados : {len(ips)}")
    log(f"  OK (senha aceita)     : {len(ok_ips)}")
    log(f"  SENHA ERRADA          : {len(wrong_ips)}")
    log(f"  Offline / sem resposta: {len(offline_ips)}")

    if offline_ips:
        log("\n[LISTA] IPs offline ou sem resposta:")
        for ip in offline_ips:
            log(f"  - {ip}")

    # sugestões de comando para inventory_scan.py
    if ok_ips:
        ips_str = ",".join(ok_ips)
        log("\n[COMANDO SUGERIDO] Rodar inventário APENAS nos IPs com senha OK:")
        log("""python tools\inventory_scan.py ^
  --alvo {ips} ^
  --usuario {user} ^
  --senha {pwd}
""".format(ips=ips_str, user=args.usuario, pwd=args.senha))

    if wrong_ips:
        log("\n[ATENÇÃO] Foram encontradas câmeras com SENHA ERRADA:")
        for ip in wrong_ips:
            log(f"  - {ip}")
        log("\nVocê pode agora informar senhas específicas para essas câmeras.")
        log("Se não quiser informar agora, basta apertar ENTER direto.\n")

        for ip in wrong_ips:
            try:
                nova = input(f"Nova senha para {ip} (ou ENTER para pular): ").strip()
            except EOFError:
                nova = ""
            if not nova:
                continue
            # para cada IP com nova senha, sugerimos um comando dedicado:
            log("""[COMANDO SUGERIDO] Para {ip}:
python tools\inventory_scan.py ^
  --alvo {ip} ^
  --usuario {user} ^
  --senha {pwd}
""".format(ip=ip, user=args.usuario, pwd=nova))

    log("\n[INFO] Fim da checagem de senha. Nenhuma câmera foi travada: 1 tentativa por IP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
