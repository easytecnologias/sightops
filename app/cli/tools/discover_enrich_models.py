#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
discover_enrich_models.py — Enriquecimento simples de modelos a partir do cam-discovery.csv

Objetivo:
- Ler o CSV gerado pelo discover_cameras.py
- Tentar descobrir/ajustar o modelo (modelo_guess) usando:
  1) Scopes ONVIF (onvif_scopes)
  2) Página HTTP (title/corpo) com regex de modelo

Uso típico:

    python tools\discover_enrich_models.py ^
      --csv .\saida\cam-discovery.csv ^
      --out .\saida\cam-discovery.enriched.csv

"""

import argparse
import csv
import re
import socket
from dataclasses import dataclass, asdict
from typing import List, Optional

try:
    import requests
except ImportError:
    requests = None


@dataclass
class Row:
    ip: str
    mac: str = ""
    http_port: str = ""
    rtsp_port: str = ""
    open_ports: str = ""
    fabricante_guess: str = ""
    modelo_guess: str = ""
    device_type: str = ""
    is_onvif: str = ""
    onvif_xaddrs: str = ""
    onvif_scopes: str = ""
    ssdp_server: str = ""
    ssdp_location: str = ""
    brand_source: str = ""
    model_source: str = ""
    http_title: str = ""
    last_error: str = ""


MODEL_PATTERNS = [
    # Intelbras / OEM
    r"VIP[-\s_]?[0-9A-Za-z]+",      # VIP 3230 B G2 etc.
    r"VHD[-\s_]?[0-9A-Za-z]+",      # VHD 3120 etc.
    r"iME[-\s_]?[0-9A-Za-z]+",      # iME 1120 etc.
    r"iMX[-\s_]?[0-9A-Za-z]+",      # iMX xxxx

    # Hikvision / HiLook
    r"DS-[0-9A-Z-]+",                # DS-2CD2347G2-LU etc.

    # Dahua
    r"(DH-)?IPC-[0-9A-Z-]+",         # IPC-HFWxxxx

    # Genérico: V + 3/4 dígitos (V3001, V3050, etc.)
    r"V[0-9]{3,4}",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_onvif_model(scopes: str) -> Optional[str]:
    """
    Tenta extrair o modelo a partir dos scopes ONVIF.
    Ex.: onvif://www.onvif.org/model/VIP-3230-B-G2
    """
    if not scopes:
        return None
    scopes = scopes.strip()
    parts = scopes.split()
    candidates = []
    for p in parts:
        if "onvif://" not in p:
            continue
        lower = p.lower()
        if "/model/" in lower:
            val = p.split("/model/", 1)[-1]
            candidates.append(val)
        elif "/name/" in lower:
            val = p.split("/name/", 1)[-1]
            candidates.append(val)
    if not candidates:
        return None
    # pega o mais longo (tende a ser o mais completo)
    model = max(candidates, key=len)
    model = model.replace("_", " ")
    return model.strip()


def http_get_model(ip: str, http_port: str, timeout: float = 1.5) -> (Optional[str], Optional[str], Optional[str]):
    """
    Faz um GET na página HTTP e tenta extrair:
    - title
    - modelo via regex
    - possivelmente complementar fabricante
    Retorna (title, modelo_guess, brand_guess_parcial)
    """
    if requests is None:
        return None, None, None

    port = 80
    try:
        if http_port:
            port = int(str(http_port).strip())
    except ValueError:
        port = 80

    url = f"http://{ip}:{port}/"
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return None, None, None

    text = resp.text or ""
    lower = text.lower()

    # título
    m = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    title = m.group(1).strip() if m else None

    # tenta modelos nas patterns
    model_found = None
    for pattern in MODEL_PATTERNS:
        m2 = re.search(pattern, text, flags=re.IGNORECASE)
        if m2:
            model_found = m2.group(0).strip()
            break

    brand_found = None
    if "intelbras" in lower:
        brand_found = "Intelbras"
    elif "hikvision" in lower or "hilook" in lower:
        brand_found = "Hikvision/HiLook"
    elif "dahua" in lower:
        brand_found = "Dahua"

    return title, model_found, brand_found


def load_rows(csv_path: str) -> List[Row]:
    rows: List[Row] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(Row(**{field: r.get(field, "") for field in Row.__dataclass_fields__.keys()}))
    return rows


def write_rows(rows: List[Row], out_path: str) -> None:
    fieldnames = list(Row.__dataclass_fields__.keys())
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Enriquecer modelo_guess a partir de ONVIF scopes e HTTP.")
    parser.add_argument("--csv", required=True, help="CSV de entrada (cam-discovery.csv)")
    parser.add_argument("--out", default=r".\\saida\\cam-discovery.enriched.csv", help="CSV de saída enriquecido")
    parser.add_argument("--timeout", type=float, default=1.5, help="Timeout para requisições HTTP (padrão: 1.5s)")
    parser.add_argument("--max-http", type=int, default=100, help="Máximo de IPs para tentar HTTP (para não ficar muito lento)")

    args = parser.parse_args(argv)

    rows = load_rows(args.csv)
    log(f"[INFO] Lidas {len(rows)} linhas de {args.csv}")

    # 1) Tenta enriquecer via ONVIF scopes
    onvif_count = 0
    for row in rows:
        if row.modelo_guess:
            continue
        model = parse_onvif_model(row.onvif_scopes)
        if model:
            row.modelo_guess = model
            row.model_source = row.model_source or "onvif_scopes"
            onvif_count += 1

    log(f"[INFO] Modelos encontrados via ONVIF scopes: {onvif_count}")

    # 2) HTTP (title + regex), limitado a max-http
    if requests is None:
        log("[WARN] 'requests' não instalado, pulando etapa HTTP.")
    else:
        http_count = 0
        http_attempts = 0
        for row in rows:
            if http_attempts >= args.max_http:
                break
            if row.modelo_guess:
                continue

            # só tenta HTTP se temos alguma porta web ou open_ports
            if not row.http_port and not row.open_ports:
                continue

            http_attempts += 1
            title, model, brand = http_get_model(row.ip, row.http_port, timeout=args.timeout)
            updated = False

            if title and not row.http_title:
                row.http_title = title
                updated = True

            if model and not row.modelo_guess:
                row.modelo_guess = model
                row.model_source = row.model_source or "http_regex"
                updated = True

            if brand and not row.fabricante_guess:
                row.fabricante_guess = brand
                row.brand_source = row.brand_source or "http_body"
                updated = True

            if updated:
                http_count += 1
                log(f"[HTTP] {row.ip} -> modelo={row.modelo_guess!r} fabricante={row.fabricante_guess!r}")

        log(f"[INFO] Modelos enriquecidos via HTTP: {http_count} (tentativas HTTP: {http_attempts})")

    write_rows(rows, args.out)
    log(f"[INFO] Arquivo enriquecido salvo em: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
