from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import pdv_store

# Ponto de venda (auditoria de caixa). Escrita declarada em security._role_rules.
# /api/pdv/coletor/ e PUBLICA no ApiAuthMiddleware: quem autentica e o token do
# caixa, conferido aqui. O cliente sai do token, nunca do que o coletor manda.
router = APIRouter(prefix="/api/pdv", tags=["pdv"])

_MAX_CORPO = 2 * 1024 * 1024


def _executar(fn, *args, **kw) -> Dict[str, Any]:
    try:
        return fn(*args, **kw)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _hoje() -> str:
    return datetime.now().strftime("%Y-%m-%d")  # container em America/Sao_Paulo


# ------------------------------------------------------------------ coletor

@router.post("/coletor/lote")
async def api_pdv_coletor_lote(request: Request) -> Dict[str, Any]:
    caixa = pdv_store.autenticar(
        str(request.headers.get("x-pdv-caixa") or "").strip(),
        str(request.headers.get("x-pdv-token") or "").strip(),
    )
    if not caixa:
        raise HTTPException(status_code=401, detail="caixa ou token invalido")
    corpo = await request.body()
    if len(corpo) > _MAX_CORPO:
        raise HTTPException(status_code=413, detail="lote grande demais")
    try:
        import json
        payload = json.loads(corpo.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="json invalido")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="json invalido")
    tok = set_current_tenant_slug(caixa["tenant_slug"])
    try:
        return _executar(pdv_store.receber_lote, caixa, payload)
    finally:
        reset_current_tenant_slug(tok)


# ------------------------------------------------------------------ caixas

@router.get("/caixas")
def api_pdv_caixas() -> Dict[str, Any]:
    return {"ok": True, "caixas": pdv_store.listar_caixas()}


@router.post("/caixas")
def api_pdv_salvar_caixa(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "caixa": _executar(pdv_store.salvar_caixa, payload)}


@router.post("/caixas/{caixa_id}/token")
def api_pdv_novo_token(caixa_id: str) -> Dict[str, Any]:
    return {"ok": True, **_executar(pdv_store.novo_token, caixa_id)}


@router.delete("/caixas/{caixa_id}")
def api_pdv_excluir_caixa(caixa_id: str) -> Dict[str, Any]:
    return _executar(pdv_store.excluir_caixa, caixa_id)


@router.post("/caixas/{caixa_id}/acesso")
def api_pdv_acesso(caixa_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """IP do caixa na loja + usuario/senha SSH (senha cifrada; em branco mantem)."""
    from app.services import pdv_instalador
    return {"ok": True, "acesso": _executar(pdv_instalador.salvar_acesso, caixa_id, payload)}


@router.post("/caixas/{caixa_id}/instalar")
def api_pdv_instalar(caixa_id: str, request: Request) -> Dict[str, Any]:
    """Instala o coletor no caixa pelo tunel do conector (nunca pelo IP publico)."""
    from app.services import pdv_instalador
    from app.services.connector_service import get_connector

    cx = next((c for c in pdv_store.listar_caixas() if c["id"] == caixa_id), None)
    if not cx:
        raise HTTPException(status_code=404, detail="Caixa não encontrado.")
    conector = get_connector(cx["connector_id"], include_token=False, enforce_tenant=True) if cx["connector_id"] else None
    base = str((conector or {}).get("public_base_url") or "").strip() or _base_publica(request)
    return _executar(pdv_instalador.iniciar_instalacao, caixa_id, base)


@router.get("/instalacao/{job_id}")
def api_pdv_instalacao_andamento(job_id: str) -> Dict[str, Any]:
    """Passos da instalacao em andamento (so do cliente da sessao)."""
    from app.services import pdv_instalador
    return _executar(pdv_instalador.andamento, job_id)


@router.post("/caixas/{caixa_id}/coletor")
def api_pdv_coletor_status(caixa_id: str) -> Dict[str, Any]:
    """Situacao do servico do coletor no caixa (so leitura, pelo tunel)."""
    from app.services import pdv_instalador
    return _executar(pdv_instalador.status, caixa_id)


def _base_publica(request: Request) -> str:
    from app.api.endpoints.connectors import _request_public_base_url
    return _request_public_base_url(request)


@router.post("/caixas/{caixa_id}/reprocessar")
def api_pdv_reprocessar(caixa_id: str, dia: str) -> Dict[str, Any]:
    return _executar(pdv_store.reprocessar_dia, caixa_id, dia)


# ------------------------------------------------------------------ consultas

@router.get("/resumo")
def api_pdv_resumo(dia: str = "", caixa_id: str = "") -> Dict[str, Any]:
    return {"ok": True, **_executar(pdv_store.resumo_dia, dia or _hoje(), caixa_id)}


@router.get("/cupons")
def api_pdv_cupons(dia: str = "", caixa_id: str = "", operador: str = "", situacao: str = "",
                   texto: str = "", de: str = "", ate: str = "") -> Dict[str, Any]:
    return {"ok": True, "cupons": _executar(pdv_store.buscar_cupons, dia or _hoje(), caixa_id=caixa_id,
                                            operador=operador, situacao=situacao, texto=texto,
                                            hora_de=de, hora_ate=ate)}


@router.get("/cupons/{caixa_id}/{dia}/{cupom}")
def api_pdv_cupom(caixa_id: str, dia: str, cupom: str) -> Dict[str, Any]:
    return {"ok": True, **_executar(pdv_store.detalhe_cupom, caixa_id, dia, cupom)}


@router.get("/video/{caixa_id}")
def api_pdv_video(caixa_id: str, ts: str, antes: int = 20, depois: int = 20) -> Dict[str, Any]:
    """Parametros do trecho para /api/nvr/driver/trecho/iniciar (horario ja no relogio do gravador)."""
    return {"ok": True, **_executar(pdv_store.janela_video, caixa_id, ts, antes, depois)}


@router.post("/relogio/{caixa_id}")
def api_pdv_medir_relogio(caixa_id: str) -> Dict[str, Any]:
    """Le a hora do gravador (so leitura, getCurrentTime) e guarda a diferenca para o caixa."""
    from app.api.endpoints.recorder_driver import _abrir
    from app.services.recorder_driver import ErroDriver
    from app.services.recorder_media_service import sem_senha

    cx = next((c for c in pdv_store.listar_caixas() if c["id"] == caixa_id), None)
    if not cx:
        raise HTTPException(status_code=404, detail="Caixa não encontrado.")
    if not cx["gravador_host"]:
        raise HTTPException(status_code=400, detail="Este caixa ainda não tem gravador configurado.")
    try:
        g = _abrir(cx["gravador_host"], 80, cx["connector_id"])
    except ValueError as exc:  # conector recusado pelo vnat: nega com motivo, nao 500
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        medida = g.relogio()
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=sem_senha(str(exc))) from exc
    return {**_executar(pdv_store.registrar_relogio_dvr, caixa_id, medida["diferenca_s"]), "leitura": medida}


@router.get("/ao-vivo/{caixa_id}")
def api_pdv_ao_vivo(caixa_id: str) -> Dict[str, Any]:
    return {"ok": True, **_executar(pdv_store.ao_vivo, caixa_id)}
