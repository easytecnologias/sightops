from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from app.services.intelbras_switch_service import collect_switch_snapshot
from app.services.hikvision_switch_service import collect_switch_snapshot as collect_hikvision_switch_snapshot
from app.models.requests import SwitchCollectMacsRequest
from app.services.switch_service import collect_macs, list_macs, clear_macs, set_port_poe, set_port_enabled

router = APIRouter(prefix="/api/switch", tags=["switch"])


def _as_str(v: Any) -> str:
    return str(v or "").strip()


@router.post("/intelbras/inspect")
def inspect_intelbras_switch(payload: Dict[str, Any]) -> Dict[str, Any]:
    host = _as_str(payload.get("host") or payload.get("ip"))
    user = _as_str(payload.get("user") or payload.get("username"))
    password = _as_str(payload.get("pass") or payload.get("password"))
    include_config = bool(payload.get("include_config", False))
    timeout = float(payload.get("timeout") or 10.0)
    port = int(payload.get("port") or 23)

    if not host or not user or not password:
        return {"ok": False, "error": "host/user/pass sao obrigatorios"}

    try:
        snapshot = collect_switch_snapshot(
            host=host,
            username=user,
            password=password,
            include_config=include_config,
            port=port,
            timeout=timeout,
        )
    except Exception as e:
        return {"ok": False, "error": str(e) or repr(e) or "falha ao consultar switch"}

    return {"ok": True, "host": host, "platform": "intelbras_telnet", "snapshot": snapshot}


@router.post("/hikvision/inspect")
def inspect_hikvision_switch(payload: Dict[str, Any]) -> Dict[str, Any]:
    host = _as_str(payload.get("host") or payload.get("ip"))
    user = _as_str(payload.get("user") or payload.get("username"))
    password = _as_str(payload.get("pass") or payload.get("password"))
    timeout = float(payload.get("timeout") or 10.0)
    port = int(payload.get("port") or 80)

    if not host or not user or not password:
        return {"ok": False, "error": "host/user/pass sao obrigatorios"}

    try:
        snapshot = collect_hikvision_switch_snapshot(
            host=host,
            username=user,
            password=password,
            include_config=False,
            port=port,
            timeout=timeout,
        )
    except Exception as e:
        return {"ok": False, "error": str(e) or repr(e) or "falha ao consultar switch"}

    return {"ok": True, "host": host, "platform": "hikvision_http", "snapshot": snapshot}


@router.post("/collect-macs")
def api_switch_collect_macs(req: SwitchCollectMacsRequest) -> Dict[str, Any]:
    return collect_macs(req)


@router.get("/rows")
def api_switch_rows(site: str = "") -> Dict[str, Any]:
    return list_macs(site=site)


@router.post("/clear")
def api_switch_clear(site: str = "") -> Dict[str, Any]:
    return clear_macs(site=site)


@router.post("/port/poe")
def api_switch_port_poe(payload: Dict[str, Any]) -> Dict[str, Any]:
    switch_ip = _as_str(payload.get("switch_ip"))
    site = _as_str(payload.get("site"))
    port_name = _as_str(payload.get("port"))
    enabled = bool(payload.get("enabled"))
    if not switch_ip or not port_name:
        return {"ok": False, "error": "switch_ip/port sao obrigatorios"}
    return set_port_poe(switch_ip, site, port_name, enabled)


@router.post("/port/enabled")
def api_switch_port_enabled(payload: Dict[str, Any]) -> Dict[str, Any]:
    switch_ip = _as_str(payload.get("switch_ip"))
    site = _as_str(payload.get("site"))
    port_name = _as_str(payload.get("port"))
    enabled = bool(payload.get("enabled"))
    if not switch_ip or not port_name:
        return {"ok": False, "error": "switch_ip/port sao obrigatorios"}
    return set_port_enabled(switch_ip, site, port_name, enabled)
