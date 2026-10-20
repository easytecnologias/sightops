from __future__ import annotations

from typing import Any, Dict
from app.core import permissions
from fastapi import APIRouter, HTTPException

from app.services.monitoring_service import (
    config_health,
    list_entities,
    list_onu_signal_history,
    list_profiles,
    monitoring_summary,
    refresh_from_inventory,
    set_profile_threshold,
)
from app.services.zabbix_monitoring_service import sync_monitoring_to_zabbix
from app.services.telegram_notification_service import get_telegram_config, process_monitoring_notifications, save_telegram_config, test_telegram

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/summary")
def api_monitoring_summary() -> Dict[str, Any]:
    return monitoring_summary(sites=permissions.sites_da_sessao())


@router.get("/entities")
def api_monitoring_entities(entity_type: str = "", status: str = "", limit: int = 500) -> Dict[str, Any]:
    rows = permissions.filtrar_por_site(list_entities(entity_type=entity_type, status=status, limit=limit), ("site",))
    return {"ok": True, "count": len(rows), "entities": rows}


@router.get("/profiles")
def api_monitoring_profiles() -> Dict[str, Any]:
    rows = list_profiles()
    return {"ok": True, "count": len(rows), "profiles": rows}


@router.put("/profiles/{profile_key}")
def api_monitoring_profile_put(profile_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return {"ok": True, "profile": set_profile_threshold(profile_key, payload.get("failure_threshold"))}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/health")
def api_monitoring_health() -> Dict[str, Any]:
    return config_health()


@router.get("/onu-signals")
def api_monitoring_onu_signals(entity_key: str, limit: int = 720) -> Dict[str, Any]:
    rows = list_onu_signal_history(entity_key, limit)
    return {"ok": True, "entity_key": entity_key, "count": len(rows), "samples": rows}


@router.post("/refresh")
def api_monitoring_refresh() -> Dict[str, Any]:
    result = refresh_from_inventory()
    result["zabbix"] = sync_monitoring_to_zabbix()
    result["telegram"] = process_monitoring_notifications()
    result["summary"] = monitoring_summary()
    return result


@router.post("/zabbix-sync")
def api_monitoring_zabbix_sync() -> Dict[str, Any]:
    return sync_monitoring_to_zabbix()


@router.get("/telegram")
def api_monitoring_telegram_get() -> Dict[str, Any]:
    return {"ok": True, **get_telegram_config()}


@router.put("/telegram")
def api_monitoring_telegram_put(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, **save_telegram_config(payload)}


@router.post("/telegram/test")
def api_monitoring_telegram_test() -> Dict[str, Any]:
    return test_telegram()
