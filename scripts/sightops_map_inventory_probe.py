from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path("/app")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.tenant_context import set_current_tenant_slug  # noqa: E402
from app.api.endpoints.tools import (  # noqa: E402
    _list_kmz_generated_layers,
    _list_kmz_import_layers,
    tenant_kmz_imported_geojson_path,
    tenant_kmz_imported_path,
)
from app.core.tenant_context import tenant_kmz_input_dir, tenant_kmz_output_dir  # noqa: E402


def file_info(path: Path) -> dict[str, object]:
    return {"path": str(path), "exists": path.exists(), "size": path.stat().st_size if path.exists() else 0}


def list_files(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    out = []
    for item in sorted(path.rglob("*")):
        if item.is_file() and item.suffix.lower() in {".kmz", ".kml", ".geojson", ".json"}:
            out.append({
                "path": str(item),
                "rel": str(item.relative_to(path)),
                "size": item.stat().st_size,
            })
    return out


def summarize_layer(layer: dict) -> dict[str, object]:
    return {
        "id": layer.get("id"),
        "label": layer.get("label"),
        "original_name": layer.get("original_name"),
        "features_count": layer.get("features_count"),
        "source": layer.get("source", "imported"),
        "source_layer_id": layer.get("source_layer_id", ""),
    }


def main() -> None:
    tenant = sys.argv[1] if len(sys.argv) > 1 else ""
    if tenant:
        set_current_tenant_slug(tenant)
    imported = _list_kmz_import_layers(include_features=False)
    generated = _list_kmz_generated_layers(include_features=False)
    print(json.dumps({
        "tenant": tenant or "(legacy/default)",
        "latest_imported": file_info(tenant_kmz_imported_path(tenant) if tenant else tenant_kmz_imported_path()),
        "latest_geojson": file_info(tenant_kmz_imported_geojson_path(tenant) if tenant else tenant_kmz_imported_geojson_path()),
        "imported_count": len(imported),
        "generated_count": len(generated),
        "imported": [summarize_layer(item) for item in imported],
        "generated": [summarize_layer(item) for item in generated],
        "input_files": list_files(tenant_kmz_input_dir(tenant) if tenant else tenant_kmz_input_dir()),
        "output_files": list_files(tenant_kmz_output_dir(tenant) if tenant else tenant_kmz_output_dir()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
