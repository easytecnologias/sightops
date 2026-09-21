from typing import Optional
from PIL import Image
import json, time, os

def compute_phash(path: str, size: int = 32) -> str:
    try:
        img = Image.open(path).convert("L").resize((size, size))
    except Exception:
        return "0"*16
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for px in pixels:
        bits = (bits << 1) | (1 if px > avg else 0)
    return f"{bits:016x}"[-16:]

class PhashCache:
    def __init__(self, cache_path: str, ttl_seconds: int = 900):
        self.cache_path = cache_path
        self.ttl = ttl_seconds
        self._load()

    def _load(self):
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def save(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_recent_url(self, phash: str) -> Optional[str]:
        now = time.time()
        rec = self.data.get(phash)
        if not rec:
            return None
        if now - rec.get("ts", 0) > self.ttl:
            return None
        return rec.get("url")

    def remember(self, phash: str, url: str):
        self.data[phash] = {"ts": time.time(), "url": url}
        self.save()
