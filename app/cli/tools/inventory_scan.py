#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inventory_scan.py — JSON-only wrapper (legacy compat).

Este wrapper existia para gerar cam-inventory.csv via src/run_all.py.
Agora o projeto é JSON-only. Mantemos este arquivo apenas por compatibilidade,
delegando para tools/inventory_dry.py e gravando em saida/cam-inventory.json.
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "tools"
OUT_JSON = ROOT / "saida" / "cam-inventory.json"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--alvo", required=True)
    p.add_argument("--usuario", required=True)
    p.add_argument("--senha", required=True)
    args = p.parse_args()

    cmd = [
        sys.executable,
        str(TOOLS / "inventory_dry.py"),
        "--alvo", args.alvo,
        "--usuario", args.usuario,
        "--senha", args.senha,
        "--out", str(OUT_JSON),
    ]
    print("[inventory_scan] JSON-only:", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=str(ROOT))
    sys.exit(rc)

if __name__ == "__main__":
    main()
