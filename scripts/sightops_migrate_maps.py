from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path("/app") if Path("/app/app").exists() else Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.tenant_context import (  # noqa: E402
    set_current_tenant_slug,
    tenant_input_dir,
    tenant_kmz_imported_geojson_path,
    tenant_kmz_imported_path,
    tenant_kmz_input_dir,
)
from app.api.endpoints.tools import _kmz_layer_paths, _safe_name  # noqa: E402
from app.api.endpoints.tools import _list_kmz_import_layers  # noqa: E402
from app.services.kmz_ops import kmz_to_geojson  # noqa: E402


def copy_file(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: sightops_migrate_maps.py <source_dir> <target_tenant>")

    source_dir = Path(sys.argv[1]).resolve()
    target_tenant = sys.argv[2].strip().lower()
    if not source_dir.exists():
        raise SystemExit(f"source_dir not found: {source_dir}")
    if not target_tenant:
        raise SystemExit("target_tenant required")

    set_current_tenant_slug(target_tenant)

    source_input_dir = source_dir / "input" if (source_dir / "input").exists() else source_dir
    src_imported = source_input_dir / "imported.kmz"
    src_geojson = source_input_dir / "imported.geojson"
    src_kmz_dir = source_input_dir / "kmz"

    candidates = []
    if src_kmz_dir.exists():
        candidates.extend(sorted(src_kmz_dir.glob("*.kmz"), key=lambda p: p.stat().st_mtime))
    should_import_latest_as_layer = src_imported.exists() and all(p.name != src_imported.name for p in candidates)
    if should_import_latest_as_layer and candidates:
        try:
            should_import_latest_as_layer = src_imported.stat().st_size not in {p.stat().st_size for p in candidates}
        except Exception:
            pass
    if should_import_latest_as_layer:
        candidates.append(src_imported)

    imported_layers = []
    skipped_layers = []
    existing_by_original = {
        str(item.get("original_name") or "").strip().lower(): str(item.get("id") or "").strip()
        for item in _list_kmz_import_layers(include_features=False)
    }
    existing_originals = set(existing_by_original)
    now = datetime.now().isoformat(timespec="seconds")
    for src in candidates:
        if src.name.strip().lower() in existing_originals:
            skipped_layers.append(src.name)
            continue
        layer_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_safe_name(src.name)}"
        layer_kmz, layer_geojson, layer_meta = _kmz_layer_paths(layer_id)
        copy_file(src, layer_kmz)
        try:
            geojson = kmz_to_geojson(layer_kmz)
        except Exception:
            # Se o legado ja trouxe geojson do ultimo import, use-o para esse caso.
            if src.name == src_imported.name and src_geojson.exists():
                geojson = json.loads(src_geojson.read_text(encoding="utf-8") or "{}")
            else:
                raise
        layer_geojson.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = {
            "id": layer_id,
            "original_name": src.name,
            "label": Path(src.name).stem,
            "created_at": now,
            "features_count": len(geojson.get("features") or []),
            "migrated_from": "homologation",
        }
        layer_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        imported_layers.append(meta)

    # Compatibilidade com botoes antigos e com a ferramenta de aplicar coordenadas.
    if candidates:
        latest = candidates[-1]
        copy_file(latest, tenant_kmz_imported_path(target_tenant))
        latest_geojson = None
        if latest.name == src_imported.name and src_geojson.exists():
            latest_geojson = json.loads(src_geojson.read_text(encoding="utf-8") or "{}")
        else:
            latest_geojson = kmz_to_geojson(tenant_kmz_imported_path(target_tenant))
        tenant_kmz_imported_geojson_path(target_tenant).write_text(
            json.dumps(latest_geojson, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        layer_id = imported_layers[-1]["id"] if imported_layers else existing_by_original.get(latest.name.strip().lower(), "")
        if layer_id:
            (tenant_input_dir(target_tenant) / "imported.meta.json").write_text(
                json.dumps({"original_name": latest.name, "layer_id": layer_id}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # Preserve os KMZ brutos em input/kmz para historico/import futuro.
    if src_kmz_dir.exists():
        dst_kmz_dir = tenant_kmz_input_dir(target_tenant)
        for src in sorted(src_kmz_dir.glob("*.kmz")):
            copy_file(src, dst_kmz_dir / src.name)

    print(json.dumps({
        "ok": True,
        "target_tenant": target_tenant,
        "layers_created": len(imported_layers),
        "layers_skipped_existing": skipped_layers,
        "layers": imported_layers,
        "latest_imported": str(tenant_kmz_imported_path(target_tenant)),
        "latest_geojson": str(tenant_kmz_imported_geojson_path(target_tenant)),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
