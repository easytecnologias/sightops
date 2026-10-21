from __future__ import annotations

from typing import Any, Dict
from app.core import permissions
from fastapi import APIRouter, Body, HTTPException, Request

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


# --------------------------------------------------------------------------- Notificacoes por site
# Configuracoes > Notificacoes: grupos do Telegram, que sites e avisos cada um
# recebe, vincular grupo pelo robo da Easy. So administrador (_role_rules).

def _notif_erro(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _notif_usuario(request: Request) -> Dict[str, Any]:
    return getattr(request.state, "current_user", None) or {}


@router.get("/notificacoes")
def api_notificacoes(request: Request) -> Dict[str, Any]:
    from app.core.tenant_context import get_current_tenant_slug
    from app.services import notificacoes_service as N

    sites = permissions.filtrar_por_site(
        [{"site": s["name"], "equipamentos": s["equipamentos"]} for s in permissions.sites_do_cliente(get_current_tenant_slug())],
        ("site",))
    return {"ok": True, **N.config_publica(), "sites": sites, "resumo": N.resumo_envios(),
            "dono_plataforma": bool(_notif_usuario(request).get("is_platform_admin"))}


@router.post("/notificacoes/grupos")
def api_notificacoes_grupo_salvar(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from app.services import notificacoes_service as N

    return {"ok": True, "grupo": _notif_erro(N.salvar_grupo, payload if isinstance(payload, dict) else {})}


@router.delete("/notificacoes/grupos/{grupo_id}")
def api_notificacoes_grupo_excluir(grupo_id: str) -> Dict[str, Any]:
    from app.services import notificacoes_service as N

    if not N.excluir_grupo(grupo_id):
        raise HTTPException(status_code=404, detail="grupo nao encontrado")
    return {"ok": True}


@router.post("/notificacoes/grupos/{grupo_id}/teste")
def api_notificacoes_grupo_teste(grupo_id: str) -> Dict[str, Any]:
    from app.services import notificacoes_service as N

    return _notif_erro(N.testar_grupo, grupo_id)


@router.post("/notificacoes/grupos/{grupo_id}/sites")
def api_notificacoes_grupo_sites(grupo_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from app.services import notificacoes_service as N

    modo = "tirar" if str((payload or {}).get("modo") or "") == "tirar" else "adicionar"
    return {"ok": True, "grupo": _notif_erro(N.definir_sites, grupo_id, list((payload or {}).get("sites") or []), modo)}


@router.put("/notificacoes/sinal")
def api_notificacoes_sinal(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from app.services import notificacoes_service as N

    return {"ok": True, "sinal": _notif_erro(N.salvar_sinal, (payload or {}).get("warn_rx", -27), (payload or {}).get("critical_rx", -29))}


@router.post("/notificacoes/vincular")
def api_notificacoes_vincular(request: Request) -> Dict[str, Any]:
    from app.core.tenant_context import get_current_tenant_slug
    from app.services import notificacoes_service as N

    return {"ok": True, **_notif_erro(N.novo_codigo, get_current_tenant_slug(), str(_notif_usuario(request).get("username") or ""))}


@router.get("/notificacoes/vincular/{codigo}")
def api_notificacoes_vincular_status(codigo: str) -> Dict[str, Any]:
    from app.core.tenant_context import get_current_tenant_slug
    from app.services import notificacoes_service as N

    return {"ok": True, **N.situacao_codigo(get_current_tenant_slug(), codigo)}


@router.get("/notificacoes/robo-easy")
def api_notificacoes_robo_get(request: Request) -> Dict[str, Any]:
    from app.services import notificacoes_service as N

    if not _notif_usuario(request).get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="somente a Easy configura o robo")
    return {"ok": True, **N.bot_easy_publico()}


@router.put("/notificacoes/robo-easy")
def api_notificacoes_robo_put(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    from app.services import notificacoes_service as N

    if not _notif_usuario(request).get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="somente a Easy configura o robo")
    return {"ok": True, **_notif_erro(N.salvar_bot_easy, (payload or {}).get("token") or "", (payload or {}).get("url_publica") or "")}
