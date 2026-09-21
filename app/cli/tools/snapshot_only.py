#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snapshot_only.py – captura snapshot de UM endpoint.

Uso:
  python -m app.cli.tools.snapshot_only --alvo 45.164.52.138:81 --usuario admin --senha 123

Ele chama o módulo app.services.camsnapshot.cli com --snapshot e grava em saida/cam-inventory.json
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--alvo", required=True, help="IP ou IP:PORTA do endpoint")
    p.add_argument("--usuario", required=True, help="Usuário HTTP")
    p.add_argument("--senha", required=True, help="Senha HTTP")
    p.add_argument("--saida", default="saida", help="Diretório de saída (padrão: saida)")
    p.add_argument("--fast", action="store_true", help="Modo rápido")
    args = p.parse_args()

    cmd = [
        sys.executable, "-m", "app.services.camsnapshot.cli",
        "--alvo", args.alvo,
        "--saida", str(Path(args.saida)),
        "--usuario", args.usuario,
        "--senha", args.senha,
        "--snapshot",
    ]
    if args.fast:
        cmd.append("--fast")

    print("[snapshot_only] Comando:", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=str(ROOT))
    raise SystemExit(rc)

if __name__ == "__main__":
    main()
