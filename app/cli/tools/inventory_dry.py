#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""inventory_dry.py – inventário "seco" (sem snapshot, sem uploads).

Gera APENAS saida/cam-inventory.json (JSON-only).
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--alvo", required=True)
    p.add_argument("--usuario", required=True)
    p.add_argument("--senha", required=True)
    p.add_argument("--out", default=str(ROOT / "saida" / "cam-inventory.json"))
    args = p.parse_args()

    cmd = [
        sys.executable, "-m", "app.services.camsnapshot.cli",
        "--alvo", args.alvo,
        "--saida", str(Path(args.out)),
        "--usuario", args.usuario,
        "--senha", args.senha,
        "--fast",
    ]
    print("[inventory_dry] Comando:", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=str(ROOT))
    sys.exit(rc)

if __name__ == "__main__":
    main()
