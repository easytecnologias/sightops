from __future__ import annotations

import hashlib
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse
from html import unescape

import requests
from PIL import Image, ImageOps

from app.core.paths import DATA_DIR

ASSET_DIR = DATA_DIR / "windows-hardware-assets"
CACHE_PATH = ASSET_DIR / "photo-cache.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 SightOps/1.0"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _cache_key(query: str) -> str:
    return hashlib.sha256(_text(query).lower().encode("utf-8")).hexdigest()[:24]


def _load_cache() -> Dict[str, Any]:
    try:
        if CACHE_PATH.exists():
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _image_ext(url: str, content_type: str = "") -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".png") or "png" in content_type:
        return ".png"
    if path.endswith(".webp") or "webp" in content_type:
        return ".webp"
    return ".jpg"


def _download_image(url: str, stem: str) -> str:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=12)
    resp.raise_for_status()
    content_type = str(resp.headers.get("content-type") or "").lower()
    if "image" not in content_type and not urlparse(url).path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        raise ValueError("URL nao retornou imagem.")
    with Image.open(BytesIO(resp.content)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1100, 850))
        out = ASSET_DIR / f"{stem}{_image_ext(url, content_type)}"
        img.save(out, quality=88)
    return str(out)


def _duckduckgo_vqd(query: str) -> str:
    resp = requests.get(
        "https://duckduckgo.com/",
        params={"q": query, "iax": "images", "ia": "images"},
        headers={"User-Agent": UA},
        timeout=12,
    )
    resp.raise_for_status()
    match = re.search(r"vqd=['\"]?([\d-]+)", resp.text)
    return match.group(1) if match else ""


def _duckduckgo_images(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    vqd = _duckduckgo_vqd(query)
    if not vqd:
        return []
    resp = requests.get(
        "https://duckduckgo.com/i.js",
        params={"l": "br-pt", "o": "json", "q": query, "vqd": vqd, "f": ",,,", "p": "1"},
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://duckduckgo.com/",
        },
        timeout=12,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") if isinstance(data, dict) else []
    return [r for r in results[:limit] if isinstance(r, dict)]


def _extract_result_links(html: str) -> List[str]:
    links: list[str] = []
    for match in re.finditer(r'class=["\']result__a["\'][^>]+href=["\']([^"\']+)', html, re.I):
        href = unescape(match.group(1))
        if href and href.startswith("http") and "duckduckgo.com" not in href:
            links.append(href)
    if links:
        return links
    for match in re.finditer(r'href=["\'](https?://[^"\']+)["\']', html, re.I):
        href = unescape(match.group(1))
        if href and "duckduckgo.com" not in href and href not in links:
            links.append(href)
    return links[:8]


def _duckduckgo_web_links(query: str, limit: int = 6) -> List[str]:
    resp = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers={"User-Agent": UA, "Referer": "https://duckduckgo.com/"},
        timeout=12,
    )
    resp.raise_for_status()
    return _extract_result_links(resp.text)[:limit]


def _page_image(url: str) -> Dict[str, Any]:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=12)
    resp.raise_for_status()
    html = resp.text[:500000]
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else ""
    patterns = [
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            image = unescape(match.group(1))
            if image.startswith("//"):
                image = "https:" + image
            elif image.startswith("/"):
                parsed = urlparse(url)
                image = f"{parsed.scheme}://{parsed.netloc}{image}"
            if image.startswith("http"):
                return {"image": image, "url": url, "title": title}
    return {}


def _first_image(query: str, kind: str, label: str) -> Dict[str, Any]:
    key = _cache_key(query)
    cache = _load_cache()
    cached = cache.get(key)
    if isinstance(cached, dict) and cached.get("local_path") and Path(str(cached["local_path"])).exists():
        return cached
    results: list[dict[str, Any]] = []
    try:
        results.extend(_duckduckgo_images(query, limit=6))
    except Exception:
        pass
    if not results:
        try:
            for link in _duckduckgo_web_links(query + " product image", limit=6):
                page_asset = _page_image(link)
                if page_asset:
                    results.append(page_asset)
        except Exception:
            pass
    for result in results:
        image_url = _text(result.get("image") or result.get("thumbnail"))
        if not image_url:
            continue
        try:
            local_path = _download_image(image_url, f"{kind}-{key}")
            asset = {
                "kind": kind,
                "label": label,
                "query": query,
                "title": _text(result.get("title")),
                "source_url": _text(result.get("url")),
                "image_url": image_url,
                "local_path": local_path,
                "provider": "DuckDuckGo Images",
            }
            cache[key] = asset
            _save_cache(cache)
            return asset
        except Exception:
            continue
    return {}


def _queries_for_row(row: Dict[str, Any]) -> List[tuple[str, str, str]]:
    queries: list[tuple[str, str, str]] = []
    maker = _text(row.get("manufacturer"))
    model = _text(row.get("model"))
    if maker or model:
        queries.append(("computador", "Computador", f"{maker} {model} product photo".strip()))
        queries.append(("placa", "Placa mae", f"{maker} {model} motherboard".strip()))
    motherboard = row.get("motherboard") if isinstance(row.get("motherboard"), dict) else {}
    mb_model = _text(motherboard.get("model"))
    mb_maker = _text(motherboard.get("manufacturer"))
    if mb_model:
        queries.append(("placa", "Placa mae", f"{mb_maker} {mb_model} motherboard".strip()))
    for module in (row.get("memory_modules") or [])[:2]:
        if not isinstance(module, dict):
            continue
        part = _text(module.get("part_number"))
        mem_maker = _text(module.get("manufacturer"))
        ddr = _text(module.get("ddr"))
        if part or mem_maker:
            queries.append(("memoria", "Memoria RAM", f"{mem_maker} {part} {ddr} memory module".strip()))
    for disk in (row.get("disks") or [])[:2]:
        if not isinstance(disk, dict):
            continue
        disk_model = _text(disk.get("model"))
        disk_maker = _text(disk.get("manufacturer"))
        media = _text(disk.get("media_type"))
        if disk_model:
            queries.append(("disco", "SSD/HD", f"{disk_maker} {disk_model} {media}".strip()))
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for item in queries:
        key = item[2].lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out[:6]


def enrich_windows_rows_with_photos(rows: List[Dict[str, Any]], per_row: int = 4) -> Dict[str, Any]:
    updated: list[dict[str, Any]] = []
    found = 0
    for row in rows or []:
        current = dict(row)
        assets = []
        for kind, label, query in _queries_for_row(current):
            asset = _first_image(query, kind, label)
            if asset:
                assets.append(asset)
            if len(assets) >= per_row:
                break
        current["photo_assets"] = assets
        found += len(assets)
        updated.append(current)
    return {"ok": True, "rows": updated, "assets": found}
