#!/usr/bin/env python3
import io, os, re, sys

RUNALL = os.path.join("src", "run_all.py")
TAGS = [
    ("# --- camsnapshot v1.12 post hook ---", "# --- end v1.12 hook ---"),
    ("# --- camsnapshot v1.11 post hook ---", "# --- end v1.11 hook ---"),
]

NEW_BLOCK = r"""
# --- camsnapshot v1.13 post hook ---
import atexit as _cs_atexit
def _cs_post_v113():
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

        snapshot = discover_snapshot("output/snapshot")
        after_snapshot(csv_path=inventory_csv, snapshot_files=snapshot, verbose=True)
        tidy_inventory(inventory_csv)
        inventory_xlsx = os.path.splitext(inventory_csv)[0] + ".xlsx"
        create_xlsx_from_csv(inventory_csv, inventory_xlsx)
    except Exception as _e:
        print("[v1.13 post hook] aviso:", _e)
_cs_atexit.register(_cs_post_v113)
# --- end v1.13 hook ---
"""

def main():
    if not os.path.isfile(RUNALL):
        print(f"[v1.13] Arquivo não encontrado: {RUNALL}")
        sys.exit(1)

    with io.open(RUNALL, "r", encoding="utf-8") as f:
        src = f.read()

    replaced = False
    for start_tag, end_tag in TAGS:
        if start_tag in src:
            pattern = re.compile(re.escape(start_tag) + r".*?" + re.escape(end_tag), re.DOTALL)
            src = pattern.sub(NEW_BLOCK.strip(), src)
            replaced = True
            break

    if not replaced:
        # se já existir 1.13, não duplica
        if "# --- camsnapshot v1.13 post hook ---" in src:
            print("[v1.13] Já atualizado.")
            sys.exit(0)
        src = src + "\n\n" + NEW_BLOCK.strip()

    with io.open(RUNALL, "w", encoding="utf-8") as f:
        f.write(src)

    print("[v1.13] Hook atualizado (estilo e CF no XLSX).")
    sys.exit(0)

if __name__ == "__main__":
    main()
