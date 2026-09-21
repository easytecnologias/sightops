# camsnapshot/thumbs.py
from __future__ import annotations
from pathlib import Path
from typing import Dict
from PIL import Image

def ensure_thumbnails(snapshot_dir: str|Path = "output/snapshot",
                      thumbs_dir: str|Path = "saida/thumbs",
                      max_w: int = 240, max_h: int = 135) -> Dict[str, str]:
    """
    Gera miniaturas .jpg em saida/thumbs e retorna dict {ip: thumb_path}.
    """
    snap_dir = Path(snapshot_dir)
    out_dir = Path(thumbs_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping: Dict[str, str] = {}

    for jpg in sorted(snap_dir.glob("*.jpg")):
        ip = jpg.stem.replace("__", ":").replace("_", ".")
        thumb = out_dir / jpg.name  # mesmo nome
        if not thumb.exists() or thumb.stat().st_mtime < jpg.stat().st_mtime:
            try:
                with Image.open(jpg) as im:
                    im.thumbnail((max_w, max_h))
                    im.convert("RGB").save(thumb, "JPEG", quality=85)
            except Exception as e:
                print(f"[thumbs] Falha em {jpg.name}: {e}")
                continue
        mapping[ip] = str(thumb)
    return mapping
