#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OLT 8820i – Listar ONUs da PON desejada

Uso CLI:

python .\tools\olt_8820i_list_onus.py ^
  --olt-ip 10.80.80.5 ^
  --user admin ^
  --password admin ^
  --pon 1 ^
  --out .\saida\olt-onu-list.csv

Gera um CSV contendo:
pon, onu_id, serial, oper_status, omci_status, rx_olt, rx_onu, distance_km, uptime
"""

import argparse
import csv
import time
import re
from typing import List, Dict

import paramiko  # type: ignore[import]


def ssh_cmd(client: paramiko.SSHClient, cmd: str) -> str:
    """Executa um comando na OLT e retorna a saída como string."""
    stdin, stdout, stderr = client.exec_command(cmd)
    time.sleep(0.3)
    return stdout.read().decode(errors="ignore")


def parse_onu_status(output: str, pon: int) -> List[Dict]:
    """
    Faz o parse da saída de:
        onu status gpon <pon>

    A regex abaixo pode ser ajustada caso o formato mude.
    """
    linhas = output.splitlines()
    tabela: List[Dict] = []

    # Exemplo de linha típica (ajuste se necessário):
    # 1   8B3E3755  Active  OK   -20.52 dBm  -18.83 dBm  0.758  7:22:52:22
    rgx = re.compile(
        r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(-?\d+(?:\.\d+)?)?\s*dBm\s+(-?\d+(?:\.\d+)?)?\s*dBm\s+([\d\.]+)\s+([\d:]+)"
    )

    for linha in linhas:
        m = rgx.search(linha)
        if m:
            tabela.append(
                {
                    "pon": pon,
                    "onu_id": m.group(1).strip(),
                    "serial": m.group(2).strip(),
                    "oper_status": m.group(3).strip(),
                    "omci_status": m.group(4).strip(),
                    "rx_olt": m.group(5) or "",
                    "rx_onu": m.group(6) or "",
                    "distance_km": m.group(7),
                    "uptime": m.group(8),
                }
            )

    return tabela


# ============
# FUNÇÃO P/ BACKEND (FastAPI)
# ============

def list_onus_8820i(olt_ip: str, user: str, password: str, pon: int) -> List[Dict]:
    """
    Lista ONUs da OLT Intelbras 8820i em uma PON específica e retorna lista de dicts.
    Pode ser usada direto pelo backend FastAPI.
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(olt_ip, username=user, password=password, look_for_keys=False, allow_agent=False)

    try:
        out = ssh_cmd(client, f"onu status gpon {pon}")
        tabela = parse_onu_status(out, pon)
        return tabela
    finally:
        client.close()


# ============
# CLI TRADICIONAL
# ============

def main() -> None:
    p = argparse.ArgumentParser(description="Lista ONUs da OLT Intelbras 8820i (PON específica).")
    p.add_argument("--olt-ip", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--pon", required=True, help="Número da PON (ex: 1)")
    p.add_argument("--out", required=True, help="CSV de saída")

    args = p.parse_args()
    pon = int(args.pon)

    print(f"[INFO] Conectando na OLT {args.olt_ip} ...")

    tabela = list_onus_8820i(args.olt_ip, args.user, args.password, pon)

    if not tabela:
        print("[WARN] Nenhuma ONU encontrada! (Parse vazio)")
    else:
        print(f"[INFO] ONUs encontradas: {len(tabela)}")

    # Gera CSV
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "pon",
                "onu_id",
                "serial",
                "oper_status",
                "omci_status",
                "rx_olt",
                "rx_onu",
                "distance_km",
                "uptime",
            ],
        )
        w.writeheader()
        for row in tabela:
            w.writerow(row)

    print(f"[INFO] CSV gerado: {args.out}")


if __name__ == "__main__":
    main()
