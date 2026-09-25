from __future__ import annotations

from app.api.endpoints.olt import api_olt_registry_telemetry
from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services.monitoring_service import list_monitoring_tenants, refresh_from_inventory
from app.services.olt_registry import list_olts
from app.services.zabbix_monitoring_service import sync_monitoring_to_zabbix


def main() -> None:
    for tenant_slug in list_monitoring_tenants():
        token = set_current_tenant_slug(tenant_slug)
        try:
            print({"tenant": tenant_slug, "stage": "start"}, flush=True)
            for olt in list_olts(include_inactive=False):
                olt_id = int(olt["id"])
                try:
                    result = api_olt_registry_telemetry(olt_id)
                except Exception as exc:
                    result = {"ok": False, "olt_id": olt_id, "error": str(exc)}
                print({"tenant": tenant_slug, "telemetry": result}, flush=True)
            print({"tenant": tenant_slug, "monitoring": refresh_from_inventory()}, flush=True)
            print({"tenant": tenant_slug, "zabbix": sync_monitoring_to_zabbix()}, flush=True)
        finally:
            reset_current_tenant_slug(token)


if __name__ == "__main__":
    main()
