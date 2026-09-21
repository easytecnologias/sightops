#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kmz_from_inventory.py — gera KMZ enriquecido usando o inventário (JSON ou CSV).

Uso (JSON):
python .\tools\kmz_from_inventory.py ^
  --json .\saida\cam-inventory.json ^
  --kmz-in .\entrada\kmz ^
  --kmz-out .\saida\kmz

Compat (CSV antigo):
python .\tools\kmz_from_inventory.py ^
  --csv .\saida\cam-inventory.csv ^
  --kmz-in .\entrada\kmz ^
  --kmz-out .\saida\kmz
"""

import argparse
import os
import json
from pathlib import Path
import sys

# Descobre a raiz do projeto e coloca no sys.path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.camsnapshot.inventory_loader import load_inventory_by_name
from app.services.camsnapshot.kmz_enricher import enrich_folder


def _unwrap_items(data):
    # aceita: lista, {meta, items}, {items}, {cpes}
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            return [x for x in data["items"] if isinstance(x, dict)]
        if isinstance(data.get("cpes"), list):
            return [x for x in data["cpes"] if isinstance(x, dict)]
    return []


def load_inventory_json(path: Path):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = _unwrap_items(data)
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description="Enriquece arquivos KMZ usando o inventário.")
    p.add_argument("--json", default="", help="Caminho para cam-inventory.json (recomendado).")
    p.add_argument("--csv", default="", help="Caminho para cam-inventory.csv (legado).")
    p.add_argument(
        "--kmz-in",
        default=str(ROOT / "data" / "input" / "kmz"),
        help="Pasta com os KMZ de entrada (default: ./data/input/kmz)",
    )
    p.add_argument(
        "--kmz-out",
        default=str(ROOT / "saida" / "kmz"),
        help="Pasta de saída para KMZ enriquecidos (default: ./saida/kmz)",
    )

    args = p.parse_args()

    kmz_in_dir = Path(args.kmz_in)
    kmz_out_dir = Path(args.kmz_out)

    if not kmz_in_dir.is_dir():
        print("[KMZ] Pasta de entrada não existe:", kmz_in_dir)
        return

    os.makedirs(kmz_out_dir, exist_ok=True)

    inventory = []

    # Preferir JSON
    if args.json:
        inv_json = Path(args.json)
        if not inv_json.exists():
            print("[ERRO] Inventário JSON não encontrado:", inv_json)
            return
        inventory = load_inventory_json(inv_json)

    # Fallback CSV (antigo)
    elif args.csv:
        inv_csv = Path(args.csv)
        if not inv_csv.exists():
            print("[ERRO] Inventário CSV não encontrado:", inv_csv)
            return
        inventory = load_inventory_by_name(str(inv_csv))

    else:
        # default: tenta saida/cam-inventory.json
        inv_json = ROOT / "saida" / "cam-inventory.json"
        if inv_json.exists():
            inventory = load_inventory_json(inv_json)
        else:
            inv_csv = ROOT / "saida" / "cam-inventory.csv"
            if inv_csv.exists():
                inventory = load_inventory_by_name(str(inv_csv))

    if not inventory:
        print("[KMZ] Inventário vazio/sem dados, pulando.")
        return

    outs = enrich_folder(str(kmz_in_dir), inventory, str(kmz_out_dir))
    if outs:
        print(f"[KMZ] {len(outs)} arquivo(s) enriquecidos em: {kmz_out_dir}")
        for pth in outs:
            print("   -", pth)
    else:
        print("[KMZ] Nenhum .kmz encontrado em", kmz_in_dir)


if __name__ == "__main__":
    main()
