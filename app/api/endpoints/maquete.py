from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.endpoints.auth import current_user
from app.services import maquete_store

# Maquete 3D (Integracoes > Maquete 3D). Escrita declarada em
# security._role_rules; DELETE vira so admin pela regra central de exclusao.
router = APIRouter(prefix="/api/maquete", tags=["maquete"])


def _executar(fn, *args) -> Dict[str, Any]:
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/projetos")
def api_maquete_listar() -> Dict[str, Any]:
    return _executar(maquete_store.listar)


@router.post("/projetos")
async def api_maquete_criar(
    arquivo: UploadFile = File(...),
    nome: str = Form(""),
    local: str = Form(""),
    observacao: str = Form(""),
    user: Dict[str, Any] = Depends(current_user),
) -> Dict[str, Any]:
    pdf = await arquivo.read()
    quem = str(user.get("name") or user.get("username") or "")
    return _executar(maquete_store.criar, nome, arquivo.filename or "", pdf, quem, local, observacao)


@router.get("/projetos/{projeto_id}")
def api_maquete_obter(projeto_id: str) -> Dict[str, Any]:
    return _executar(maquete_store.obter, projeto_id)


@router.put("/projetos/{projeto_id}")
def api_maquete_salvar(projeto_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(maquete_store.salvar, projeto_id, payload)


@router.delete("/projetos/{projeto_id}")
def api_maquete_excluir(projeto_id: str) -> Dict[str, Any]:
    return _executar(maquete_store.excluir, projeto_id)


@router.get("/projetos/{projeto_id}/textura/{arquivo}")
def api_maquete_textura(projeto_id: str, arquivo: str):
    try:
        arq = maquete_store.textura(projeto_id, arquivo)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return FileResponse(arq, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
