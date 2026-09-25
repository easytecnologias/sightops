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


def name(feature: dict) -> str:
    return str((feature.get("properties") or {}).get("name") or "").strip()


def point_keys(features: list[dict]) -> set[str]:
    out = set()
    for f in features or []:
        if str((f.get("geometry") or {}).get("type") or "").lower() != "point":
            continue
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        out.add(f"{name(f).lower()}|{float(coords[1]):.6f}|{float(coords[0]):.6f}")
    return out


def signature(features: list[dict]) -> str:
    return "||".join(sorted(point_keys(features))[:80])


def overlaps(keys: set[str], imported_sets: list[set[str]]) -> bool:
    if not keys:
        return False
    for imported in imported_sets:
        if not imported:
            continue
        common = sum(1 for key in keys if key in imported)
        if common / min(len(keys), len(imported)) >= 0.8:
            return True
    return False


def main() -> None:
    tenant = sys.argv[1] if len(sys.argv) > 1 else "easy-tecnologias"
    set_current_tenant_slug(tenant)
    imported = _list_kmz_import_layers(include_features=True)
    generated = _list_kmz_generated_layers(include_features=True)
    imported_sets = [point_keys(x.get("features") or []) for x in imported]
    imported_sigs = {signature(x.get("features") or []) for x in imported if signature(x.get("features") or [])}
    imported_ids = {str(x.get("id") or "") for x in imported}
    visible_generated = []
    hidden_generated = []
    for layer in generated:
        keys = point_keys(layer.get("features") or [])
        sig = signature(layer.get("features") or [])
        source_layer_id = str(layer.get("source_layer_id") or "")
        hidden = source_layer_id in imported_ids or sig in imported_sigs or overlaps(keys, imported_sets)
        (hidden_generated if hidden else visible_generated).append({
            "label": layer.get("label"),
            "features": len(keys),
            "source_layer_id": source_layer_id,
        })
    print(json.dumps({
        "tenant": tenant,
        "visible_layers": [{"label": x.get("label"), "kind": "imported", "features": len(point_keys(x.get("features") or []))} for x in imported] + [{"label": x.get("label"), "kind": "generated", "features": x.get("features")} for x in visible_generated],
        "hidden_generated_duplicates": hidden_generated,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
