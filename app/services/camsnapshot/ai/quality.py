"""
Basic quality metrics without OpenCV.
"""
from typing import Dict
from PIL import Image, ImageStat, ImageFilter

def _blur_score(img: Image.Image) -> float:
    e = img.convert("L").filter(ImageFilter.FIND_EDGES)
    stat = ImageStat.Stat(e)
    var = sum((v**2 for v in stat.rms)) if isinstance(stat.rms, list) else stat.rms**2
    return float(var)

def _exposure(img: Image.Image) -> float:
    g = img.convert("L")
    stat = ImageStat.Stat(g)
    mean = stat.mean[0] if isinstance(stat.mean, list) else stat.mean
    return float(mean) / 255.0

def _black_percent(img: Image.Image, thr: int = 10) -> float:
    g = img.convert("L")
    hist = g.histogram()
    black = sum(hist[:thr+1])
    total = sum(hist)
    return 100.0 * (black / max(1, total))

def score(path: str) -> Dict[str, float]:
    try:
        img = Image.open(path)
    except Exception:
        return {"blur_score": 0.0, "exposure": 0.0, "black_pct": 100.0, "quality": 0.0}
    b = _blur_score(img)
    e = _exposure(img)
    k = _black_percent(img)
    quality = max(0.0, min(1.0, (b / 500.0))) * (1.0 - min(1.0, k/100.0))
    return {"blur_score": float(b), "exposure": float(e), "black_pct": float(k), "quality": float(quality)}
