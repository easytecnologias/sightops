from app.core.tenant_context import set_current_tenant_slug
from app.services.monitoring_service import list_entities, monitoring_summary, refresh_from_inventory


set_current_tenant_slug("default")
print(refresh_from_inventory())
rows = list_entities(entity_type="onu", limit=2000)
print({
    "onu_visible": len(rows),
    "onu_unknown": sum(1 for row in rows if row.get("status") == "unknown"),
    "summary": monitoring_summary().get("types", {}).get("onu", {}),
})
