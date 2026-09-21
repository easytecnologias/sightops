import json
from pathlib import Path
from rich.console import Console

console = Console()

JSON_FIELDS = ["ip", "mac", "fabricante", "modelo", "titulo", "snapshot_path", "status"]

def save_json(path, rows):
    """Salva inventário como JSON (lista de dicts)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows or [], f, indent=2, ensure_ascii=False)

def load_json(path):
    """Carrega inventário JSON. Retorna lista (ou [])."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []
