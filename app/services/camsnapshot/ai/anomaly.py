from typing import Optional
import json, os, statistics

class AnomalyTracker:
    def __init__(self, path: str, window: int = 20):
        self.path = path
        self.window = window
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.db = json.load(f)
        except Exception:
            self.db = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.db, f, ensure_ascii=False, indent=2)

    def update(self, ip: str, blur: float, exposure: float, black_pct: float) -> Optional[str]:
        hist = self.db.get(ip) or {"blur": [], "exposure": [], "black": []}
        for key, val in (("blur", blur), ("exposure", exposure), ("black", black_pct)):
            arr = hist[key]
            arr.append(float(val))
            if len(arr) > self.window:
                arr.pop(0)
            hist[key] = arr
        self.db[ip] = hist
        self.save()
        reason = None
        try:
            if len(hist["blur"]) >= 5:
                mu = statistics.mean(hist["blur"][:-1])
                sd = statistics.pstdev(hist["blur"][:-1]) or 1.0
                if hist["blur"][-1] < mu - 3*sd:
                    reason = "blur_spike"
            if len(hist["black"]) >= 5:
                mu = statistics.mean(hist["black"][:-1])
                sd = statistics.pstdev(hist["black"][:-1]) or 1.0
                if hist["black"][-1] > mu + 3*sd:
                    reason = reason or "dark_spike"
        except Exception:
            pass
        return reason
