#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from app.services.camsnapshot.hooks import after_snapshot, discover_snapshot

def main():
    parser = argparse.ArgumentParser(description="Publica snapshot no ImgBox e atualiza CSV (se informado).")
    parser.add_argument("--snapshot-dir", default="output/snapshot")
    parser.add_argument("--csv", default=None)
    args = parser.parse_args()

    load_dotenv()
    enable = os.getenv("IMGBOX_ENABLE", "0")
    print(f"[ImgBox] IMGBOX_ENABLE={enable}")
    snaps = discover_snapshot(args.snapshot_dir)
    print(f"[ImgBox] Encontrados {len(snaps)} arquivo(s) em '{args.snapshot_dir}'.")

    if not snaps:
        print("[ImgBox] Nada para enviar. Verifique o diretório e a extensão dos arquivos.")
        sys.exit(2)

    uploads = after_snapshot(args.csv, snaps, verbose=True)
    if not uploads:
        # Mostra as últimas linhas do relatório de erro
        rpt = os.path.join("saida", "imgbox_report.txt")
        if os.path.isfile(rpt):
            print("\n[ImgBox] Resumo do relatório (últimas linhas):")
            with open(rpt, "r", encoding="utf-8") as f:
                lines = f.readlines()[-20:]
                for ln in lines:
                    print(ln.rstrip())
        print("[ImgBox] Nenhum upload concluído.")
        sys.exit(3)
    print("[ImgBox] Finalizado com sucesso. Relatório em 'saida\\imgbox_report.txt'")

if __name__ == "__main__":
    main()
