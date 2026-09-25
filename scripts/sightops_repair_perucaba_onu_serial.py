from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.tenant_context import set_current_tenant_slug
from app.services.db_store import load_olt_cpe_state, save_olt_cpe_state
from app.services.olt_service import _sync_camera_inventory_from_olt_rows


set_current_tenant_slug("default")
state = load_olt_cpe_state() or {}
rows = [row for row in (state.get("cpes") or state.get("rows") or []) if isinstance(row, dict)]
updated = 0
for row in rows:
    if (
        str(row.get("olt_ip") or "").strip() == "10.80.80.5"
        and str(row.get("pon") or "").strip() == "7"
        and str(row.get("onu_id") or row.get("onu") or "").strip() == "4"
        and str(row.get("onu_serial") or "").strip().upper() == "0A4FCEA8"
    ):
        row["onu_serial"] = "ITBS0A4FCEA8"
        updated += 1
state["cpes"] = rows
state.pop("rows", None)
save_olt_cpe_state(state)
print({"olt_rows_updated": updated, **_sync_camera_inventory_from_olt_rows(rows)})
