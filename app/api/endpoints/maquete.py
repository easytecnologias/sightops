from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

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


@router.get("/precos")
def api_maquete_precos() -> Dict[str, Any]:
    return _executar(maquete_store.precos)


@router.put("/precos")
def api_maquete_salvar_precos(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(maquete_store.salvar_precos, payload)


@router.post("/pdf/{projeto_id}")
def api_maquete_pdf(projeto_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(current_user)) -> Response:
    """PDF do projeto (relatorio) ou do orcamento. A tela manda os dados ja
    calculados e as imagens da maquete; o projeto precisa ser deste cliente."""
    import re as _re
    import unicodedata

    from app.core.tenant_context import tenant_report_logo_path
    from app.services.maquete_pdf import gerar_pdf

    projeto = _executar(maquete_store.obter, projeto_id)["projeto"]
    logo = tenant_report_logo_path("inventory")
    usuario = str(user.get("name") or user.get("username") or "")
    pdf = gerar_pdf(projeto, payload or {}, usuario=usuario, logo=logo if logo.exists() else None)
    prefixo = "orcamento" if (payload or {}).get("tipo") == "orcamento" else "projeto-cftv"
    base = unicodedata.normalize("NFKD", f"{prefixo} {projeto.get('nome') or ''}")
    nome = _re.sub(r"[^A-Za-z0-9]+", "-", base.encode("ascii", "ignore").decode()).strip("-").lower()[:80] or prefixo
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nome}.pdf"', "Cache-Control": "no-store"})
