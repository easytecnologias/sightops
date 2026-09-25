from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path("/app") if Path("/app/app").exists() else Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.tenant_context import set_current_tenant_slug  # noqa: E402
from app.services.inventory_json import inventory_row_key, load_inventory_json, save_inventory_json  # noqa: E402
from app.api.endpoints.cameras import CameraUpdate, CamerasSaveRequest, api_cameras_save  # noqa: E402


def main() -> None:
    tenant = sys.argv[1] if len(sys.argv) > 1 else "easy-tecnologias"
    mode = sys.argv[2] if len(sys.argv) > 2 else "olt"
    site = sys.argv[3] if len(sys.argv) > 3 else "JARDINS II"
    set_current_tenant_slug(tenant)
    before = load_inventory_json(mode=mode)
    site_rows = [r for r in before if str(r.get("local") or r.get("site") or r.get("site_name") or "").strip().lower() == site.lower()]
    targets = site_rows[:2]
    result = {
        "tenant": tenant,
        "mode": mode,
        "site": site,
        "total_before": len(before),
        "site_before": len(site_rows),
        "target_keys": [inventory_row_key(r) for r in targets],
        "target_ips": [r.get("ip") for r in targets],
    }
    if len(targets) < 2:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    original = deepcopy(before)
    payload = []
    marker = "__SAVE_PROBE__"
    for idx, row in enumerate(targets, 1):
        payload.append(CameraUpdate(
            ip=str(row.get("ip") or ""),
            remote_connector_id=str(row.get("remote_connector_id") or row.get("connector_id") or ""),
            connector_id=str(row.get("remote_connector_id") or row.get("connector_id") or ""),
            remote=bool(row.get("remote") or row.get("remote_connector_id") or row.get("connector_id")),
            site=str(row.get("site") or row.get("site_name") or row.get("local") or ""),
            site_name=str(row.get("site") or row.get("site_name") or row.get("local") or ""),
            titulo=f"{row.get('titulo') or row.get('ip')}{marker}{idx}",
            fabricante=str(row.get("fabricante") or ""),
            model=str(row.get("modelo") or row.get("model") or ""),
            local=str(row.get("local") or ""),
            mac=str(row.get("mac") or ""),
            pon=str(row.get("pon") or ""),
            onu_id=str(row.get("onu_id") or ""),
            onu_name=str(row.get("onu_name") or ""),
            onu_serial=str(row.get("onu_serial") or ""),
        ))
    api_result = api_cameras_save(CamerasSaveRequest(cameras=payload), mode=mode)
    after = load_inventory_json(mode=mode)
    matched = [r for r in after if marker in str(r.get("titulo") or "")]
    result.update({
        "api_result": api_result,
        "total_after": len(after),
        "matched_after": [{"ip": r.get("ip"), "titulo": r.get("titulo"), "key": inventory_row_key(r)} for r in matched],
    })
    save_inventory_json(original, mode=mode)
    restored = load_inventory_json(mode=mode)
    result.update({
        "restored_total": len(restored),
        "markers_after_restore": len([r for r in restored if marker in str(r.get("titulo") or "")]),
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
