from __future__ import annotations
import asyncio, os
from typing import Iterable, List, Dict, Any, Optional, Tuple
import httpx
def _norm_cookie(raw: str) -> str:
    parts = []
    for seg in raw.split(";"):
        seg = seg.strip()
        if not seg or "=" not in seg:
            continue
        k, v = seg.split("=", 1)
        if k.lower() in ("path", "expires", "max-age", "domain", "secure", "httponly", "samesite"):
            continue
        parts.append(f"{k.strip()}={v.strip()}")
    return "; ".join(parts)
async def _auth_upload_async(files: Iterable[str], title: str, cookie_header: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    success: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    headers = {"Cookie": cookie_header, "User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(headers=headers, timeout=60) as client:
        await client.get("https://imgbox.com/")
        for f in files:
            try:
                resp = await client.post("https://imgbox.com/upload", data={"gallery": title}, files={"files[]": (os.path.basename(f), open(f, "rb"), "image/jpeg")}, follow_redirects=True)
                if 200 <= resp.status_code < 300 and ("imgbox.com" in (resp.text or "")):
                    success.append({"file": os.path.basename(f), "url": "https://imgbox.com", "thumbnail_url": "https://imgbox.com"})
                else:
                    failures.append({"file": os.path.basename(f), "status": "http", "error": f"status {resp.status_code}"})
            except Exception as ex:
                failures.append({"file": os.path.basename(f), "status": "exc", "error": str(ex)})
    return success, failures
def upload_to_imgbox_auth(snapshot_paths: Iterable[str], title: Optional[str] = None, cookie: Optional[str] = None) -> List[Dict[str, Any]]:
    files = [p for p in snapshot_paths if p and os.path.isfile(p)]
    if not files or not cookie:
        return []
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    cookie_header = _norm_cookie(cookie or "")
    s, f = loop.run_until_complete(_auth_upload_async(files, title or "Smart-Cams Snapshots", cookie_header))
    return s
