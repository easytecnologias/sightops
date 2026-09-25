from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.endpoints.olt import api_olt_registry_telemetry
from app.core.tenant_context import set_current_tenant_slug
from app.services.olt_registry import list_olts


set_current_tenant_slug("default")
for olt in list_olts(include_inactive=False):
    if str(olt.get("host") or "").strip() == "10.80.80.5":
        print(api_olt_registry_telemetry(int(olt["id"])))
