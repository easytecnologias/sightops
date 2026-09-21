#!/usr/bin/env python3
import io, os, re, sys

RUNALL = os.path.join("src", "run_all.py")
TAG_START = "# --- camsnapshot v1.11 post hook ---"
TAG_END   = "# --- end v1.11 hook ---"

NEW_BLOCK = r"""
# --- camsnapshot v1.12 post hook ---
import atexit as _cs_atexit
def _cs_post_v112():
    try:
        from app.services.camsnapshot.hooks import after_snapshot, discover_snapshot
        from app.services.camsnapshot.post_csv import tidy_inventory
        from app.services.camsnapshot.export_xlsx import create_xlsx_from_csv
        import sys, os

        inventory_csv = r".\\saida\\cam-inventory.csv"
        try:
            for i, tok in enumerate(sys.argv):
                if tok == "--saida" and i+1 < len(sys.argv):
                    inventory_csv = sys.argv[i+1]
                    break
        except Exception:
            pass

        # Diretório padrão de snapshot
        snapshot = discover_snapshot("output/snapshot")

        # 1) Upload + atualizar URLs no CSV
        after_snapshot(csv_path=inventory_csv, snapshot_files=snapshot, verbose=True)

        # 2) Remover 'snapshot_path' + ordenar por IP
        tidy_inventory(inventory_csv)

        # 3) Gerar XLSX bonitinho ao lado do CSV
        inventory_xlsx = os.path.splitext(inventory_csv)[0] + ".xlsx"
        create_xlsx_from_csv(inventory_csv, inventory_xlsx)

    except Exception as _e:
        print("[v1.12 post hook] aviso:", _e)
_cs_atexit.register(_cs_post_v112)
# --- end v1.12 hook ---
"""

def main():
    if not os.path.isfile(RUNALL):
        print(f"[v1.12] Arquivo não encontrado: {RUNALL}")
        sys.exit(1)

    with io.open(RUNALL, "r", encoding="utf-8") as f:
        src = f.read()

    if TAG_START in src:
        # Replace old v1.11 block with v1.12 block
        pattern = re.compile(re.escape(TAG_START) + r".*?" + re.escape(TAG_END), re.DOTALL)
        new_src = pattern.sub(NEW_BLOCK.strip(), src)
    elif "# --- camsnapshot v1.12 post hook ---" in src:
        print("[v1.12] Já atualizado.")
        sys.exit(0)
    else:
        # No previous block: just append
        new_src = src + "\n\n" + NEW_BLOCK.strip()

    with io.open(RUNALL, "w", encoding="utf-8") as f:
        f.write(new_src)

    print("[v1.12] Hook atualizado (gera XLSX formatado).")
    sys.exit(0)

if __name__ == "__main__":
    main()
