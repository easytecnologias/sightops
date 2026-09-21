#!/usr/bin/env python3
import io, os, sys

RUNALL = os.path.join("src", "run_all.py")
HOOK_TAG = "# --- camsnapshot v1.11 post hook ---"

BLOCK = f"""{HOOK_TAG}
import atexit as _cs_atexit
def _cs_post_v111():
    try:
        from app.services.camsnapshot.hooks import after_snapshot, discover_snapshot
        from app.services.camsnapshot.post_csv import tidy_inventory
        import sys
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
    except Exception as _e:
        print("[v1.11 post hook] aviso:", _e)
_cs_atexit.register(_cs_post_v111)
# --- end v1.11 hook ---
"""

def main():
    if not os.path.isfile(RUNALL):
        print(f"[inject] Arquivo não encontrado: {RUNALL}")
        sys.exit(1)
    with io.open(RUNALL, "r", encoding="utf-8") as f:
        src = f.read()
    if HOOK_TAG in src:
        print("[inject] Hook já presente. Nada a fazer.")
        sys.exit(0)
    with io.open(RUNALL, "a", encoding="utf-8") as f:
        f.write("\n\n" + BLOCK)
    print("[inject] Hook v1.11 adicionado ao final de src/run_all.py.")
    sys.exit(0)

if __name__ == "__main__":
    main()
