from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.tenant_context import set_current_tenant_slug
from app.services.inventory_json import load_inventory_json
from app.services.db_store import load_olt_cpe_state


set_current_tenant_slug("default")
wanted = {"30:e1:f1:1a:9b:a3", "98:2a:0a:59:ae:bd", "98:2a:0a:59:b7:4a"}
rows = [
    {key: row.get(key) for key in ("ip", "mac", "titulo", "pon", "onu_id", "onu_name", "onu_serial")}
    for row in load_inventory_json(mode="olt")
    if str(row.get("mac") or "").lower() in wanted
]
print(rows)
state = load_olt_cpe_state() or {}
print([
    {key: row.get(key) for key in ("cpe_mac", "site", "connector_id", "remote_connector_id", "pon", "onu_id", "onu_serial", "source")}
    for row in (state.get("cpes") or state.get("rows") or [])
    if str(row.get("cpe_mac") or row.get("mac") or "").lower() in wanted
])
