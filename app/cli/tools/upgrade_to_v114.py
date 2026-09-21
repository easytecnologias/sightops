#!/usr/bin/env python3
import io, os, re, sys

RUNALL = os.path.join("src", "run_all.py")
KNOWN = [
    ("# --- camsnapshot v1.13.1 post hook ---", "# --- end v1.13.1 hook ---"),
    ("# --- camsnapshot v1.13 post hook ---", "# --- end v1.13 hook ---"),
    ("# --- camsnapshot v1.12 post hook ---", "# --- end v1.12 hook ---"),
    ("# --- camsnapshot v1.11 post hook ---", "# --- end v1.11 hook ---"),
]

NEW_BLOCK = r"""
# --- camsnapshot v1.14 post hook ---
import atexit as _cs_atexit
def _cs_post_v114():
    try:
        from app.services.camsnapshot.hooks import after_snapshot, discover_snapshot
        from app.services.camsnapshot.add_ping import add_ping_to_csv
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

        # 1) Upload & atualizar URLs
        snapshot = discover_snapshot("output/snapshot")
        after_snapshot(csv_path=inventory_csv, snapshot_files=snapshot, verbose=True)

        # 2) Pingar apenas IPs online e gravar 'ping' (timeout 1000 ms)
        add_ping_to_csv(inventory_csv, timeout_ms=1000)

        # 3) Limpar & ordenar CSV por IP
        tidy_inventory(inventory_csv)

        # 4) Gerar XLSX estilizado com CF de status/ping
        inventory_xlsx = os.path.splitext(inventory_csv)[0] + ".xlsx"
        create_xlsx_from_csv(inventory_csv, inventory_xlsx)
    except Exception as _e:
        print("[v1.14 post hook] aviso:", _e)
_cs_atexit.register(_cs_post_v114)
# --- end v1.14 hook ---
"""

def main():
    if not os.path.isfile(RUNALL):
        print(f"[v1.14] Arquivo não encontrado: {RUNALL}")
        sys.exit(1)

    with io.open(RUNALL, "r", encoding="utf-8") as f:
        src = f.read()

    replaced = False
    for a,b in KNOWN:
        if a in src:
            src = re.sub(re.escape(a) + r".*?" + re.escape(b), NEW_BLOCK.strip(), src, flags=re.DOTALL)
            replaced = True
            break

    if not replaced:
        if "# --- camsnapshot v1.14 post hook ---" in src:
            print("[v1.14] Já atualizado.")
            sys.exit(0)
        src = src + "\n\n" + NEW_BLOCK.strip()

    with io.open(RUNALL, "w", encoding="utf-8") as f:
        f.write(src)

    print("[v1.14] Hook atualizado (ping + XLSX com CF).")
    sys.exit(0)

if __name__ == "__main__":
    main()
