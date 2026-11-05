from __future__ import annotations

import threading
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.endpoints.auth import current_user
from app.services import termico_store

# Alerta Termico (pessoa detectada pelo calor). Escrita declarada em
# security._role_rules; DELETE vira so admin pela regra central de exclusao.
router = APIRouter(prefix="/api/termico", tags=["termico"])


def _executar(fn, *args) -> Any:
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _quem(user: Dict[str, Any]) -> str:
    return str(user.get("name") or user.get("username") or "")


def _zabbix_agora(alerta_id: str) -> None:
    """Respondeu o alerta: o gatilho de pessoa fecha na hora, sem esperar o
    sync (~2 min). Numa thread: Zabbix lento nao segura a resposta da tela."""
    alvo = termico_store.camera_do_alerta(alerta_id)
    if not alvo:
        return
    from app.services.zabbix_monitoring_service import enviar_termico_agora
    threading.Thread(target=enviar_termico_agora, args=(alvo["tenant"], alvo["ip"], alvo["connector_id"]),
                     daemon=True, name="termico-zabbix").start()


@router.get("/cameras")
def api_termico_cameras() -> Dict[str, Any]:
    return _executar(termico_store.listar_cameras)


@router.post("/cameras")
def api_termico_adicionar(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(termico_store.adicionar, str(payload.get("ip") or ""), str(payload.get("connector_id") or ""))


@router.put("/cameras/{camera_id}")
def api_termico_salvar(camera_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(termico_store.salvar_camera, camera_id, payload)


@router.delete("/cameras/{camera_id}")
def api_termico_remover(camera_id: str) -> Dict[str, Any]:
    return _executar(termico_store.remover_camera, camera_id)


@router.get("/alertas")
def api_termico_alertas(site: str = "", situacao: str = "", camera_id: str = "", desde: str = "",
                        limite: int = 200) -> Dict[str, Any]:
    return _executar(termico_store.listar_alertas, site, situacao, camera_id, desde, limite)


@router.post("/alertas/{alerta_id}/ciente")
def api_termico_ciente(alerta_id: str, payload: Dict[str, Any] | None = None,
                       user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    p = payload or {}
    r = _executar(termico_store.marcar, alerta_id, "visto", _quem(user), "", str(p.get("comentario") or ""))
    _zabbix_agora(alerta_id)
    return r


@router.post("/alertas/{alerta_id}/falso")
def api_termico_falso(alerta_id: str, payload: Dict[str, Any],
                      user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    r = _executar(termico_store.marcar, alerta_id, "falso", _quem(user),
                  str(payload.get("motivo") or ""), str(payload.get("comentario") or ""))
    _zabbix_agora(alerta_id)
    return r


@router.get("/alertas/{alerta_id}/foto/{tipo}")
def api_termico_foto(alerta_id: str, tipo: str) -> FileResponse:
    caminho = _executar(termico_store.caminho_foto, alerta_id, tipo)
    return FileResponse(caminho, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
