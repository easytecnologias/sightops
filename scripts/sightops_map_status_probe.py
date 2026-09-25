from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path("/app") if Path("/app/app").exists() else Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.tenant_context import set_current_tenant_slug  # noqa: E402
from app.api.endpoints.tools import _list_kmz_generated_layers, _list_kmz_import_layers  # noqa: E402
from app.services.inventory_json import load_inventory_json  # noqa: E402


def extract_ip(text: object) -> str:
    m = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", str(text or ""))
    return m.group(0) if m else ""


def norm_name(text: object) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def feature_name(feature: dict) -> str:
    return str((feature.get("properties") or {}).get("name") or "").strip()


def main() -> None:
    tenant = sys.argv[1] if len(sys.argv) > 1 else "easy-tecnologias"
    mode = sys.argv[2] if len(sys.argv) > 2 else "olt"
    set_current_tenant_slug(tenant)
    cams = load_inventory_json(mode=mode)
    by_ip = {str(c.get("ip") or ""): c for c in cams if c.get("ip")}
    by_name = {norm_name(c.get("titulo")): c for c in cams if c.get("titulo")}
    layers = []
    for item in _list_kmz_generated_layers(include_features=True):
        item["_kind"] = "generated"
        layers.append(item)
    for item in _list_kmz_import_layers(include_features=True):
        item["_kind"] = "imported"
        layers.append(item)
    out = {
        "tenant": tenant,
        "mode": mode,
        "inventory_total": len(cams),
        "inventory_online": sum(1 for c in cams if str(c.get("status") or "").lower() == "online"),
        "inventory_offline": sum(1 for c in cams if str(c.get("status") or "").lower() == "offline"),
        "layers": [],
    }
    for layer in layers:
        stats = {"label": layer.get("label"), "kind": layer.get("_kind"), "features": 0, "matched": 0, "online": 0, "offline": 0, "fallback_online": 0, "fallback_offline": 0, "samples_unmatched": []}
        for f in layer.get("features") or []:
            if str((f.get("geometry") or {}).get("type") or "").lower() != "point":
                continue
            name = feature_name(f)
            desc = str((f.get("properties") or {}).get("description") or "")
            ip = extract_ip(desc) or extract_ip(name)
            cam = by_name.get(norm_name(name)) or by_ip.get(ip)
            stats["features"] += 1
            if cam:
                stats["matched"] += 1
                status = str(cam.get("status") or "").lower()
                if status == "online":
                    stats["online"] += 1
                elif status == "offline":
                    stats["offline"] += 1
            else:
                desc_upper = desc.upper()
                if "ONLINE" in desc_upper:
                    stats["fallback_online"] += 1
                elif "OFFLINE" in desc_upper:
                    stats["fallback_offline"] += 1
                if len(stats["samples_unmatched"]) < 8:
                    stats["samples_unmatched"].append({"name": name, "ip": ip})
        out["layers"].append(stats)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
