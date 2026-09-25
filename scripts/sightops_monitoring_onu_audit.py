from __future__ import annotations

from app.core.tenant_context import set_current_tenant_slug
from app.services.db_store import _conn
from app.services.olt_service import list_macs


def text(value: object) -> str:
    return str(value or "").strip()


def main() -> None:
    set_current_tenant_slug("default")
    inventory = list_macs().get("rows", [])
    current = {
        "onu:" + "|".join((
            text(row.get("connector_id") or row.get("remote_connector_id")),
            text(row.get("olt_ip")), text(row.get("pon")),
            text(row.get("onu_id") or row.get("onu") or row.get("onu_serial")),
        ))
        for row in inventory
    }
    with _conn() as connection:
        rows = connection.execute(
            "SELECT entity_key,site,display_name,status,last_checked_at,detail_json "
            "FROM monitoring_entities WHERE tenant_slug=? AND entity_type='onu' "
            "ORDER BY last_checked_at,entity_key",
            ("default",),
        ).fetchall()
    items = [dict(row) for row in rows]
    stale = [row for row in items if row["entity_key"] not in current]
    unknown = [row for row in items if row.get("status") == "unknown"]
    print({
        "inventory_rows": len(inventory), "inventory_keys": len(current),
        "monitoring_rows": len(items), "unknown": len(unknown), "stale": len(stale),
        "stale_unknown": sum(1 for row in stale if row.get("status") == "unknown"),
        "examples": stale[:10],
    })


if __name__ == "__main__":
    main()
