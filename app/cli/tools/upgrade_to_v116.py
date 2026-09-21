#!/usr/bin/env python3
import io, os, re, sys, json

RUNALL = os.path.join("src", "run_all.py")
KNOWN = [
    ("# --- camsnapshot v1.15 post hook ---", "# --- end v1.15 hook ---"),
    ("# --- camsnapshot v1.14 post hook ---", "# --- end v1.14 hook ---"),
    ("# --- camsnapshot v1.13.1 post hook ---", "# --- end v1.13.1 hook ---"),
    ("# --- camsnapshot v1.13 post hook ---", "# --- end v1.13 hook ---"),
    ("# --- camsnapshot v1.12 post hook ---", "# --- end v1.12 hook ---"),
    ("# --- camsnapshot v1.11 post hook ---", "# --- end v1.11 hook ---"),
]

NEW_BLOCK = r"""
# --- camsnapshot v1.16 post hook ---
import atexit as _cs_atexit
def _cs_post_v116():
    try:
        from app.services.camsnapshot.hooks import after_snapshot, discover_snapshot
        from app.services.camsnapshot.add_ping import add_ping_to_csv
        from app.services.camsnapshot.post_csv import tidy_inventory
        from app.services.camsnapshot.export_xlsx import create_xlsx_from_csv
        from app.services.camsnapshot.gallery_html import build_album
        import sys, os, json

        inventory_csv = r".\\saida\\cam-inventory.csv"
        album_name = None
        album_id = None
        try:
            argv = sys.argv
            for i, tok in enumerate(argv):
                if tok == "--saida" and i+1 < len(argv):
                    inventory_csv = argv[i+1]
                elif tok == "--album" and i+1 < len(argv):
                    album_name = argv[i+1]
                elif tok in ("--album-id", "--album_id") and i+1 < len(argv):
                    album_id = argv[i+1]
        except Exception:
            pass

        snapshot = discover_snapshot("output/snapshot")

        cache_path = ".albums.json"
        cache = {}
        if os.path.isfile(cache_path):
            try:
                cache = json.load(open(cache_path, "r", encoding="utf-8"))
            except Exception:
                cache = {}

        if album_name and not album_id:
            slug = (album_name or "").strip().lower()
            if slug in cache:
                album_id = cache[slug]

        if album_name:
            os.environ["IMGBB_ALBUM_NAME"] = album_name
        if album_id:
            os.environ["IMGBB_ALBUM_ID"] = album_id

        uploads = after_snapshot(csv_path=inventory_csv, snapshot_files=snapshot, verbose=True)

        if album_name and not album_id and uploads:
            out_html = build_album(album_name, uploads, out_dir="saida/albums")
            print("[Album] Album local gerado:", out_html)

        add_ping_to_csv(inventory_csv, timeout_ms=1000)
        tidy_inventory(inventory_csv)
        inventory_xlsx = os.path.splitext(inventory_csv)[0] + ".xlsx"
        create_xlsx_from_csv(inventory_csv, inventory_xlsx)

        if album_name and album_id:
            slug = (album_name or "").strip().lower()
            cache[slug] = album_id
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            print(f"[Album] Cache atualizado: {slug} -> {album_id}")

    except Exception as _e:
        print("[v1.16 post hook] aviso:", _e)
_cs_atexit.register(_cs_post_v116)
# --- end v1.16 hook ---
"""

def main():
    if not os.path.isfile(RUNALL):
        print(f"[v1.16] Arquivo não encontrado: {RUNALL}")
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
        if "# --- camsnapshot v1.16 post hook ---" in src:
            print("[v1.16] Já atualizado.")
            sys.exit(0)
        src = src + "\n\n" + NEW_BLOCK.strip()

    with io.open(RUNALL, "w", encoding="utf-8") as f:
        f.write(src)

    print("[v1.16] Hook atualizado (álbum por argumento + galeria local automática).")
    sys.exit(0)

if __name__ == "__main__":
    main()
