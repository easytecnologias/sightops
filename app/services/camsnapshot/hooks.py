from __future__ import annotations
import os, csv, glob
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from pathlib import Path
from app.services.camsnapshot.uploader_imgbb import upload_to_imgbb
from app.services.camsnapshot.uploader_imgbox import upload_to_imgbox
from app.services.camsnapshot.uploader_imgbox_auth import upload_to_imgbox_auth
from app.services.db_store import load_app_settings

def _update_csv_with_links(csv_path: str, uploads: List[Dict[str, Any]], ip_field: str = "ip") -> None:
    if not uploads or not os.path.isfile(csv_path):
        return
    base = {os.path.basename(u["file"]): u for u in uploads}
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    for col in ("img_url", "thumb_url"):
        if col not in fieldnames:
            fieldnames.append(col)
    for r in rows:
        ip = r.get(ip_field, "")
        for ext in (".jpg", ".png", ".jpeg"):
            name = f"{ip}{ext}"
            if name in base:
                r["img_url"] = base[name]["url"]
                r["thumb_url"] = base[name]["thumbnail_url"]
                break
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

def after_snapshot(csv_path: Optional[str], snapshot_files: List[str], verbose: bool = True) -> List[Dict[str, Any]]:
    load_dotenv()
    if not snapshot_files:
        if verbose: print("[Upload] Nenhum snapshot para publicar.")
        return []
    uploads: List[Dict[str, Any]] = []
    title = os.getenv("IMGBOX_GALLERY_TITLE", "Smart-Cams Snapshots")
    # Fonte única: chave configurada no frontend (data/settings.json -> imgbb_key)
    imgbb_key = ""
    try:
        settings = load_app_settings()
        if isinstance(settings, dict):
            imgbb_key = str(settings.get("imgbb_key") or settings.get("imgbb_api_key") or "").strip().strip('"')
    except Exception:
        pass
    if imgbb_key:
        if verbose: print("[Upload] Usando ImgBB (API oficial).")
        uploads = upload_to_imgbb(snapshot_files, api_key=imgbb_key, name_prefix="cam", report_path="saida/imgbb_report.txt")
    else:
        cookie = os.getenv("IMGBOX_COOKIE", "").strip().strip('"')
        if cookie:
            if verbose: print("[Upload] Usando ImgBox autenticado (cookie).")
            uploads = upload_to_imgbox_auth(snapshot_files, title=title, cookie=cookie)
        else:
            if verbose: print("[Upload] Usando ImgBox anônimo (pode falhar no Brasil).")
            uploads = upload_to_imgbox(snapshot_files, title=title)
    if verbose:
        ok = [u for u in uploads if "url" in u]
        print(f"[Upload] Sucessos: {len(ok)}")
        for u in ok[:10]:
            print(" •", u["file"], "=>", u["url"])
    if csv_path:
        _update_csv_with_links(csv_path, uploads)
        if verbose: print(f"[Upload] CSV atualizado: {csv_path}")
    return uploads

def discover_snapshot(directory: str = "output/snapshot") -> List[str]:
    files: List[str] = []
    for pat in ("*.jpg", "*.jpeg", "*.png"):
        files.extend(glob.glob(os.path.join(directory, pat)))
    return sorted(files)
