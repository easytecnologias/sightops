from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.services.connector_service import (
    accept_heartbeat,
    accept_job_result,
    accept_routeros_job_result,
    accept_register,
    build_agent_script,
    build_routeros_job_script,
    build_routeros_script,
    build_routeros_wireguard_script,
    create_connector,
    create_job,
    delete_connector,
    ensure_wireguard_tunnel,
    get_connector,
    list_connectors,
    list_jobs,
    poll_job,
    ruijie_collect_lan_inventory,
    ruijie_update_vpn,
)

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


def _agent_auth(request: Request) -> tuple[str, str]:
    connector_id = str(request.headers.get("x-sightops-connector-id") or "").strip()
    token = str(request.headers.get("x-sightops-connector-token") or "").strip()
    return connector_id, token


def _request_remote_ip(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = str(request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else ""


def _request_public_base_url(request: Request) -> str:
    proto = str(request.headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip()
    host = str(request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    if host:
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


@router.get("")
def api_connectors_list() -> Dict[str, Any]:
    return list_connectors(include_token=False)


@router.post("")
def api_connectors_create(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return create_connector(payload if isinstance(payload, dict) else {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{connector_id}")
def api_connectors_delete(connector_id: str) -> Dict[str, Any]:
    return delete_connector(connector_id)


@router.get("/{connector_id}")
def api_connectors_get(connector_id: str) -> Dict[str, Any]:
    row = get_connector(connector_id, include_token=True, enforce_tenant=True)
    if not row:
        raise HTTPException(status_code=404, detail="conector nao encontrado")
    return {"ok": True, "connector": row}


@router.get("/{connector_id}/agent-script")
def api_connector_agent_script(connector_id: str, request: Request) -> Response:
    try:
        custom_base = str(request.query_params.get("base_url") or "").strip()
        base_url = (custom_base or str(request.base_url)).rstrip("/")
        script = build_agent_script(base_url=base_url, connector_id=connector_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(
        content=script,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="sightops-agent.ps1"'},
    )


@router.get("/{connector_id}/routeros-script")
def api_connector_routeros_script(connector_id: str, request: Request) -> Response:
    try:
        custom_base = str(request.query_params.get("base_url") or "").strip()
        base_url = (custom_base or str(request.base_url)).rstrip("/")
        script = build_routeros_script(base_url=base_url, connector_id=connector_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(
        content=script,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="sightops-routeros.rsc"'},
    )


@router.post("/{connector_id}/wireguard")
def api_connector_wireguard(connector_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return ensure_wireguard_tunnel(connector_id, payload if isinstance(payload, dict) else {}, enforce_tenant=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{connector_id}/wireguard-routeros-script")
def api_connector_wireguard_routeros_script(connector_id: str) -> Response:
    try:
        script = build_routeros_wireguard_script(connector_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(
        content=script,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="sightops-routeros-wireguard.rsc"'},
    )


@router.post("/{connector_id}/ruijie/vpn")
def api_connector_ruijie_vpn(connector_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Grava/atualiza usuario, senha e a config (.ovpn) da VPN de um
    conector Ruijie ja cadastrado."""
    data = payload if isinstance(payload, dict) else {}
    try:
        return ruijie_update_vpn(
            connector_id,
            vpn_username=str(data.get("vpn_username") or ""),
            vpn_password=str(data.get("vpn_password") or ""),
            vpn_config=str(data.get("vpn_config") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{connector_id}/ruijie/lan-inventory")
def api_connector_ruijie_lan_inventory(connector_id: str) -> Dict[str, Any]:
    """Coleta o inventario da LAN de um conector Ruijie na hora (sem fila/job --
    o gateway tem IP publico e responde de imediato)."""
    try:
        return ruijie_collect_lan_inventory(connector_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{connector_id}/jobs")
def api_connector_jobs(connector_id: str) -> Dict[str, Any]:
    return list_jobs(connector_id=connector_id)


@router.post("/jobs")
def api_connector_create_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return create_job(payload if isinstance(payload, dict) else {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/agent/register")
async def api_connector_agent_register(request: Request) -> Dict[str, Any]:
    connector_id, token = _agent_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    try:
        remote_ip = _request_remote_ip(request)
        return accept_register(connector_id, token, payload if isinstance(payload, dict) else {}, remote_ip=remote_ip)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@router.post("/agent/heartbeat")
async def api_connector_agent_heartbeat(request: Request) -> Dict[str, Any]:
    connector_id, token = _agent_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    try:
        remote_ip = _request_remote_ip(request)
        return accept_heartbeat(connector_id, token, payload if isinstance(payload, dict) else {}, remote_ip=remote_ip)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@router.get("/agent/jobs/poll")
def api_connector_agent_poll(request: Request) -> Dict[str, Any]:
    connector_id, token = _agent_auth(request)
    try:
        return poll_job(connector_id, token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@router.get("/agent/routeros/job.rsc")
def api_connector_routeros_job_script(request: Request) -> Response:
    connector_id, token = _agent_auth(request)
    try:
        base_url = _request_public_base_url(request)
        script = build_routeros_job_script(base_url=base_url, connector_id=connector_id, token=token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return Response(content=script, media_type="text/plain; charset=utf-8")


@router.post("/agent/jobs/{job_id}/result")
async def api_connector_agent_result(job_id: str, request: Request) -> Dict[str, Any]:
    connector_id, token = _agent_auth(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    try:
        return accept_job_result(connector_id, token, job_id, payload if isinstance(payload, dict) else {})
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/agent/routeros/jobs/{job_id}/result")
def api_connector_routeros_result(job_id: str, request: Request) -> Dict[str, Any]:
    connector_id, token = _agent_auth(request)
    ok_text = str(request.query_params.get("ok") or "1").strip().lower()
    ok = ok_text not in {"0", "false", "no", "nao", "não"}
    result = str(request.query_params.get("result") or "").strip()
    error = str(request.query_params.get("error") or "").strip()
    try:
        return accept_routeros_job_result(connector_id, token, job_id, result, ok=ok, error=error)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/agent/routeros/jobs/{job_id}/result/{result:path}")
def api_connector_routeros_result_path(job_id: str, result: str, request: Request) -> Dict[str, Any]:
    connector_id, token = _agent_auth(request)
    try:
        return accept_routeros_job_result(connector_id, token, job_id, result, ok=True, error="")
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/agent/routeros/jobs/{job_id}/result-text")
async def api_connector_routeros_result_text(job_id: str, request: Request) -> Dict[str, Any]:
    connector_id, token = _agent_auth(request)
    try:
        body = await request.body()
    except Exception:
        body = b""
    result = body.decode("utf-8", errors="ignore").strip()
    try:
        return accept_routeros_job_result(connector_id, token, job_id, result, ok=True, error="")
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
