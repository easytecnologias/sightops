"""
OCR/Heuristics to infer model/brand from snapshot.
Uses pytesseract if available; otherwise regex/heuristics only.
"""
import re
from typing import Tuple, Optional
try:
    import pytesseract  # type: ignore
    from PIL import Image
    _HAS_TESS = True
except Exception:
    from PIL import Image
    _HAS_TESS = False

BRAND_KEYWORDS = {
    "intelbras": ["intelbras", "vip-", "vhd-"],
    "hikvision": ["hikvision", "ds-", "hik-"],
    "hilook": ["hilook", "ipc-b", "ipc-t", "ptz-"],
    "dahua": ["dahua", "ipc-h", "nvr", "xvr"],
    "axis": ["axis"],
    "multilaser": ["multilaser"],
}

MODEL_PATTERNS = [
    r"VIP-\d{3,5}[A-Z-]*",
    r"IPC-[A-Z0-9-]{3,}",
    r"DS-[2-3][A-Z0-9-]+",
    r"PTZ-[A-Z0-9-]+",
    r"VHD-\d{3,5}[A-Z-]*",
]

def _ocr_text(path: str) -> str:
    if not _HAS_TESS:
        return ""
    try:
        img = Image.open(path)
        txt = pytesseract.image_to_string(img, lang="eng")
        return txt or ""
    except Exception:
        return ""

def _regex_candidates(text: str):
    models = []
    for pat in MODEL_PATTERNS:
        for m in re.findall(pat, text, flags=re.I):
            models.append(m.upper())
    brand = None
    t = text.lower()
    for b, keys in BRAND_KEYWORDS.items():
        if any(k in t for k in keys):
            brand = b
            break
    return list(dict.fromkeys(models)), brand

def fill_gaps(snapshot_path: str, modelo: Optional[str], fabricante: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    m = modelo
    f = fabricante
    text = _ocr_text(snapshot_path)
    models, brand = _regex_candidates(text)
    if not m and models:
        m = models[0]
    if not f and brand:
        f = brand.capitalize()
    if not f and m:
        ml = m.lower()
        for b, keys in BRAND_KEYWORDS.items():
            if any(k in ml for k in keys):
                f = b.capitalize()
                break
    return m, f
