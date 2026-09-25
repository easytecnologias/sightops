"""Regrava inventarios existentes aplicando normalizacao de fabricante por modelo.

Uso:
    python scripts/sightops_fix_camera_brand_from_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _count_hikvision_model(rows: list[dict[str, Any]]) -> tuple[int, int]:
    total = 0
    hik = 0
    for row in rows:
        model = str(row.get("modelo") or row.get("model") or "").strip().upper()
        if model.startswith(("DS-", "HWI", "HWP", "HK")) or "HIKVISION" in model:
            total += 1
            if str(row.get("fabricante") or "").strip() == "Hikvision":
                hik += 1
    return total, hik


def main() -> int:
    from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
    from app.services.inventory_json import _inventory_state_key, load_inventory_json, save_inventory_json
    from app.services.db_store import get_json_state
    from app.services.monitoring_service import list_monitoring_tenants

    touched = 0
    details: list[str] = []
    for tenant in list_monitoring_tenants():
        token = set_current_tenant_slug(tenant)
        try:
            for mode in ("basic", "olt", "switch"):
                sentinel = object()
                exists = get_json_state(_inventory_state_key(mode), sentinel) is not sentinel
                if not exists:
                    continue
                rows = load_inventory_json(mode=mode) or []
                total, hik = _count_hikvision_model(rows)
                save_inventory_json(rows, mode=mode)
                touched += 1
                details.append(f"{tenant}/{mode}: rows={len(rows)} hik_model={hik}/{total}")
        finally:
            reset_current_tenant_slug(token)

    print("OK camera brand fix from model")
    print(f"modes_touched={touched}")
    for line in details:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
