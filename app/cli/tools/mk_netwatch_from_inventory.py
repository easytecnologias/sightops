import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INV = BASE / "output" / "inventory.json"
OUT = BASE / "output" / "netwatch.rsc"

if not INV.exists():
    raise FileNotFoundError(f"Inventário não encontrado: {INV}")

with open(INV, "r", encoding="utf-8") as f:
    inventory = json.load(f)

lines = []
for item in inventory:
    ip = item.get("ip")
    name = item.get("name") or item.get("title") or ip

    if not ip:
        continue

    lines.append(
        f'/tool netwatch add host={ip} interval=30s '
        f'down-script="log warning \"{name} OFFLINE\"" '
        f'up-script="log info \"{name} ONLINE\""'
    )

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"[OK] Netwatch gerado em: {OUT}")