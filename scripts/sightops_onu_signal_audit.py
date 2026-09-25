from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.db_store import load_olt_cpe_state
from app.core.tenant_context import set_current_tenant_slug


def main() -> None:
    set_current_tenant_slug("default")
    obj = load_olt_cpe_state() or {}
    rows = [row for row in (obj.get("cpes") or obj.get("rows") or []) if isinstance(row, dict)]
    signal_keys = ("onu_rx", "rx_onu", "onu_rx_power", "olt_rx", "rx_olt", "rx_power", "distance_km")
    present = Counter()
    statuses = Counter()
    examples = []
    for row in rows:
        statuses[str(row.get("oper_status") or row.get("status") or "").strip() or "<vazio>"] += 1
        found = {key: row.get(key) for key in signal_keys if str(row.get(key) or "").strip()}
        for key in found:
            present[key] += 1
        if found and len(examples) < 5:
            examples.append({"site": row.get("site"), "olt_ip": row.get("olt_ip"), "pon": row.get("pon"), "onu_id": row.get("onu_id"), **found})
    print({"rows": len(rows), "signal_fields": dict(present), "statuses": dict(statuses), "examples": examples})


if __name__ == "__main__":
    main()
