"""TR-069 das ONUs do cliente da sessao (ver app/services/tr069_service.py)."""
from __future__ import annotations

from typing import Any, Dict

from app.core import permissions
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from app.services import tr069_service as tr
from app.services import tr069_wan as wan
from app.services import tr069_ativacao as ativ

router = APIRouter(prefix="/api/tr069", tags=["tr069"])


def _autor(request: Request) -> str:
    user = getattr(request.state, "current_user", None) or {}
    return str(user.get("name") or user.get("username") or user.get("email") or "?")


def _erro(exc: Exception) -> Dict[str, Any]:
    return {"ok": False, "error": str(exc)}


@router.get("/devices")
async def listar_onus() -> Dict[str, Any]:
    try:
        dados = await run_in_threadpool(tr.listar)
    except tr.Tr069Error as exc:
        return _erro(exc)
    sites = permissions.sites_da_sessao()
    if sites is not None and isinstance(dados, dict):
        dados = {**dados, "onus": _onus_dos_sites(dados.get("onus") or [], sites)}
    return dados


def _onus_dos_sites(onus: list, sites: list) -> list:
    """ONU nao tem site proprio: vale o site da OLT dela (site da OLT ou do
    conector dela). OLT sem site conhecido fica de fora para usuario restrito."""
    from app.api.endpoints.maintenance import _site_do_conector
    from app.core.tenant_context import get_current_tenant_slug
    from app.services.db_store import _conn

    liberados = {s.strip().upper() for s in sites}
    site_da_olt: Dict[str, str] = {}
    with _conn() as c:
        for r in c.execute(
            "SELECT o.name, o.connector_id, s.name AS site FROM olts o LEFT JOIN sites s ON s.id = o.site_id WHERE o.tenant_slug=?",
            (get_current_tenant_slug(),),
        ).fetchall():
            site = str(r["site"] or "").strip() or _site_do_conector(r["connector_id"])
            site_da_olt[str(r["name"] or "").strip().upper()] = site.strip().upper()
    return [o for o in onus if isinstance(o, dict) and site_da_olt.get(str(o.get("olt") or "").strip().upper(), "") in liberados]


@router.get("/devices/{serial}")
async def detalhe_onu(serial: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(tr.detalhe, serial)
    except tr.Tr069Error as exc:
        return _erro(exc)


@router.post("/devices/{serial}/action")
async def acao_onu(serial: str, payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    acao = str((payload or {}).get("acao") or "").strip()
    try:
        return await run_in_threadpool(tr.executar, serial, acao, payload or {}, _autor(request))
    except (tr.Tr069Error, ValueError) as exc:
        return _erro(exc)


@router.get("/config")
async def ver_config() -> Dict[str, Any]:
    cfg = await run_in_threadpool(tr.garantir_credencial)  # noqa: F841 -- cria na primeira visita
    publica = await run_in_threadpool(tr.get_config_publica)
    return {"ok": True, **publica, "servidor": await run_in_threadpool(tr.saude)}


@router.post("/config")
async def salvar_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return {"ok": True, **await run_in_threadpool(tr.salvar_preferencias, payload or {})}
    except (tr.Tr069Error, ValueError) as exc:
        return _erro(exc)


@router.post("/config/trocar-senha")
async def trocar_senha() -> Dict[str, Any]:
    try:
        publica = await run_in_threadpool(tr.trocar_senha)
        sync = await run_in_threadpool(tr.sincronizar_cwmp_auth, True)
        return {"ok": True, **publica, "cwmp_auth": sync}
    except tr.Tr069Error as exc:
        return _erro(exc)


@router.post("/devices/{serial}/servicos/plano")
async def plano_servicos(serial: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Previa: o que mudaria na ONT, sem mandar nada."""
    def _plano():
        doc, _ = tr._documento_do_cliente(serial)
        plano = wan.planejar(doc, list((payload or {}).get("servicos") or []))
        return {"ok": True, **{k: v for k, v in plano.items() if not k.startswith("_")}}
    try:
        return await run_in_threadpool(_plano)
    except (tr.Tr069Error, wan.WanError, ValueError, TypeError) as exc:
        return _erro(exc)


@router.post("/devices/{serial}/servicos")
async def aplicar_servicos(serial: str, payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(
            wan.executar_plano, tr, serial, list((payload or {}).get("servicos") or []), _autor(request))
    except (tr.Tr069Error, wan.WanError, ValueError, TypeError) as exc:
        return _erro(exc)


@router.get("/jobs/{job_id}")
async def ver_job(job_id: str) -> Dict[str, Any]:
    job = wan.ver_job(job_id)
    return {"ok": True, **job} if job else {"ok": False, "error": "execucao nao encontrada"}


@router.get("/candidatas")
async def candidatas() -> Dict[str, Any]:
    try:
        return await run_in_threadpool(tr.candidatas)
    except tr.Tr069Error as exc:
        return _erro(exc)


@router.get("/ativar/{serial}")
async def plano_ativacao(serial: str) -> Dict[str, Any]:
    try:
        return await run_in_threadpool(ativ.plano, tr, serial)
    except (tr.Tr069Error, ativ.AtivacaoError, ValueError) as exc:
        return _erro(exc)


@router.post("/ativar")
async def ativar(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    p = payload or {}
    try:
        return await run_in_threadpool(ativ.ativar, tr, str(p.get("serial") or ""), str(p.get("metodo") or ""),
                                       _autor(request), str(p.get("rede_gerencia") or "").strip())
    except (tr.Tr069Error, ativ.AtivacaoError, ValueError) as exc:
        return _erro(exc)


@router.post("/config/redes-diretas")
async def salvar_redes_diretas(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """Redes de gerencia que o servidor alcanca sem tunel. So o dono da plataforma."""
    user = getattr(request.state, "current_user", None) or {}
    if not user.get("is_platform_admin"):
        return {"ok": False, "error": "so o dono da plataforma define redes diretas"}
    try:
        return {"ok": True, "redes_diretas": await run_in_threadpool(tr.salvar_redes_diretas, list((payload or {}).get("redes") or []))}
    except tr.Tr069Error as exc:
        return _erro(exc)
