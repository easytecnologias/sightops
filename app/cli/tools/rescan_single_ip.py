#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rescan_single_ip.py – refaz o inventário de UMA câmera e atualiza o cam-inventory.csv
e também o cam-inventory.json (para o cam-snapshot-web)

Uso (a partir da pasta do projeto, onde está src/ e saida/):

    python tools/rescan_single_ip.py \
        --ip 10.10.9.106 \
        --usuario admin \
        --senha global1234

Ele:
  - roda o run_all.py só para esse IP (modo seco, sem snapshot / ImgBB)
  - grava um CSV temporário com o inventário dessa câmera
  - abre o cam-inventory.csv atual
  - substitui (ou adiciona) a linha com esse IP
  - gera / atualiza o cam-inventory.json na raiz do projeto
"""

import argparse
import csv
import subprocess
import sys
import requests
import json
from requests.auth import HTTPDigestAuth
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
SAIDA = ROOT / "saida"
JSON_INV = ROOT / "cam-inventory.json"


def run_single_inventory(ip: str, usuario: str, senha: str, temp_csv: Path):
    """Roda run_all.py só para um IP, gerando um CSV temporário."""
    temp_csv.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(SRC / "run_all.py"),
        "--alvo", ip,
        "--usuario", usuario,
        "--senha", senha,
        "--saida", str(temp_csv),
        "--uploader", "none",
        "--fast",
    ]

    print("[rescan] Executando inventário só para", ip)
    print("[rescan] Comando:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        print(f"[rescan][ERRO] run_all.py retornou código {proc.returncode}", file=sys.stderr)
        sys.exit(proc.returncode)

    if not temp_csv.exists():
        print(f"[rescan][ERRO] CSV temporário não foi gerado: {temp_csv}", file=sys.stderr)
        sys.exit(1)


def load_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        raise RuntimeError(f"CSV vazio: {path}")
    header = rows[0]
    data = rows[1:]
    return header, data


def try_channel_title(ip: str, usuario: str, senha: str, timeout: float = 3.0) -> str | None:
    """Tenta obter o título do canal via CGI ChannelTitle (Dahua/Intelbras OEM)."""
    url = f"http://{ip}/cgi-bin/configManager.cgi?action=getConfig&name=ChannelTitle"
    auth_chain = [None, (usuario, senha), HTTPDigestAuth(usuario, senha)]
    for auth in auth_chain:
        try:
            if auth is None:
                r = requests.get(url, timeout=timeout)
            else:
                r = requests.get(url, auth=auth, timeout=timeout)
        except Exception:
            continue
        if r.status_code != 200 or not getattr(r, "text", ""):
            continue
        for line in r.text.splitlines():
            line = line.strip()
            if ".Name=" in line:
                raw = line.split("=", 1)[1].strip()
                if " - " in raw:
                    raw = raw.split(" - ", 1)[1].strip()
                raw = " ".join(raw.split()).upper()
                return raw or None
    return None


def save_csv(path: Path, header, data):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(data)


def csv_to_json(csv_path: Path, json_path: Path):
    """
    Converte cam-inventory.csv -> cam-inventory.json
    para o cam-snapshot-web usar diretamente.
    """
    print(f"[rescan] Atualizando JSON a partir de: {csv_path}")
    header, rows = load_csv(csv_path)

    inventario = []
    for row in rows:
        item = {}
        for i, col in enumerate(header):
            # garante que não estoura índice e sempre tenha string
            value = row[i] if i < len(row) else ""
            item[col] = value
        inventario.append(item)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(inventario, f, indent=4, ensure_ascii=False)

    print(f"[rescan] JSON atualizado: {json_path} ({len(inventario)} itens)")


def main():
    parser = argparse.ArgumentParser(
        description="Refaz inventário de uma câmera e atualiza o cam-inventory.csv e cam-inventory.json"
    )
    parser.add_argument("--ip", required=True, help="IP da câmera a ser reprocessada (ex: 10.10.9.106)")
    parser.add_argument("--usuario", required=True)
    parser.add_argument("--senha", required=True)
    args = parser.parse_args()

    ip = args.ip.strip()

    cam_inventory = SAIDA / "cam-inventory.csv"
    if not cam_inventory.exists():
        print(f"[rescan][ERRO] cam-inventory.csv não encontrado em {cam_inventory}", file=sys.stderr)
        sys.exit(1)

    temp_csv = SAIDA / f"cam-inventory-{ip.replace('.', '_')}.tmp.csv"

    # 1) roda inventário só desse IP
    run_single_inventory(ip, args.usuario, args.senha, temp_csv)

    # 2) carrega CSV temporário
    temp_header, temp_rows = load_csv(temp_csv)
    if not temp_rows:
        print("[rescan][ERRO] CSV temporário não tem linhas de dados.", file=sys.stderr)
        sys.exit(1)

    # assume que só veio uma linha para esse IP
    new_row = temp_rows[0]

    # Se o título veio vazio no CSV temporário, tenta forçar via CGI ChannelTitle
    try:
        titulo_idx = temp_header.index("titulo")
    except ValueError:
        titulo_idx = None

    if titulo_idx is not None:
        current_title = (new_row[titulo_idx] or "").strip()
        if not current_title:
            forced_title = try_channel_title(ip, args.usuario, args.senha)
            if forced_title:
                print(f"[rescan] Título preenchido via ChannelTitle: {forced_title}")
                new_row[titulo_idx] = forced_title

    # 3) carrega inventário atual
    header, rows = load_csv(cam_inventory)

    # tenta achar a coluna de IP no header
    try:
        ip_idx = header.index("ip")
    except ValueError:
        try:
            ip_idx = header.index("IP")
        except ValueError:
            print("[rescan][ERRO] Não encontrei coluna 'ip' ou 'IP' no cam-inventory.csv", file=sys.stderr)
            sys.exit(1)

    updated_rows = []
    found = False
    for r in rows:
        if len(r) > ip_idx and r[ip_idx] == ip:
            # substitui linha antiga pela nova
            updated_rows.append(new_row)
            found = True
        else:
            updated_rows.append(r)

    if not found:
        print(f"[rescan] IP {ip} não existia no inventário, adicionando nova linha.")
        updated_rows.append(new_row)
    else:
        print(f"[rescan] IP {ip} encontrado no inventário, linha atualizada.")

    # 4) grava de volta o inventário CSV (com backup)
    backup = cam_inventory.with_suffix(".csv.bak")
    if cam_inventory.exists():
        cam_inventory.replace(backup)
        print(f"[rescan] Backup salvo em: {backup}")

    save_csv(cam_inventory, header, updated_rows)
    print(f"[rescan] CSV final: {cam_inventory}")

    # 5) atualiza o cam-inventory.json na raiz do projeto
    try:
        csv_to_json(cam_inventory, JSON_INV)
    except Exception as e:
        print(f"[rescan][ERRO] Falha ao atualizar JSON: {e}", file=sys.stderr)

    # opcional: remover CSV temporário
    try:
        temp_csv.unlink()
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
