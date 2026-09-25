from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.tenant_context import set_current_tenant_slug
from app.services.db_store import load_olt_cpe_state
from app.services.olt_service import _sync_camera_inventory_from_olt_rows


set_current_tenant_slug("default")
state = load_olt_cpe_state() or {}
rows = [row for row in (state.get("cpes") or state.get("rows") or []) if isinstance(row, dict)]
print(_sync_camera_inventory_from_olt_rows(rows))
