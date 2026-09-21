#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_netwatch.py — wrapper para gerar o netwatch_setup.rsc
a partir do inventário + ImgBB, chamando mk_netwatch_from_inventory.py.

Uso:

python .\tools\generate_netwatch.py ^
  --token 123456:ABCDEF ^
  --chat -5035981509 ^
  [--links .\saida\links_imgbb.txt] ^
  [--interval 1m] ^
  [--timeout 2s]
"""

import argparse
import sys
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]  # raiz do projeto (cam-snapshot)


def main() -> None:
    p = argparse.ArgumentParser(description="Gera netwatch_setup.rsc a partir do inventário.")
    p.add_argument("--token", required=True, help="Token do bot Telegram")
    p.add_argument("--chat", required=True, help="ID do chat/grupo Telegram")
    p.add_argument(
        "--links",
        default=str(ROOT / "output" / "links_imgbb.txt"),
        help="Arquivo de links do ImgBB (default: ./output/links_imgbb.txt)",
    )
    p.add_argument("--interval", default="1m", help="Intervalo do Netwatch (default: 1m)")
    p.add_argument("--timeout", default="2s", help="Timeout do Netwatch (default: 2s)")

    args = p.parse_args()

    script = ROOT / "tools" / "mk_netwatch_from_inventory.py"

    cmd = [
        sys.executable,
        str(script),
        "--token",
        args.token,
        "--chat",
        args.chat,
        "--links",
        args.links,
        "--interval",
        args.interval,
        "--timeout",
        args.timeout,
    ]

    print("[INFO] Gerando netwatch_setup.rsc via mk_netwatch_from_inventory.py ...")
    print("[DBG] Comando:", " ".join(cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
