"""Rotas do driver de gravador (app/services/recorder_driver.py).

Ficam sob /api/nvr/ de proposito: a regra de perfil `POST /api/nvr/ -> operator`
ja cobre a escrita, sem abrir excecao nova em security.py.

A senha nunca passa pelo navegador: sai de recorder_credentials (cifrada por
tenant). O conector vem do inventario do proprio tenant, para o pedido sair
pelo IP virtual quando o cliente e isolado.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.tenant_context import tenant_scoped_path
from app.services.recorder_credentials import resolve_recorder_credential
from app.services.recorder_driver import FMT, ErroDriver, Gravador

router = APIRouter(prefix="/api/nvr/driver", tags=["nvr"])


def _conector(host: str) -> str:
    from app.api.endpoints.nvr import _recorder_connector_for_host
    try:
        return _recorder_connector_for_host(host)
    except Exception:
        return ""


def _abrir(host: str, http_port: int, connector_id: str = "") -> Gravador:
    host = str(host or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="informe o gravador")
    cred = resolve_recorder_credential(host, http_port) or {}
    if not cred.get("password"):
        raise HTTPException(status_code=428, detail="SEM_CREDENCIAL")
    try:
        return Gravador(host, cred.get("username") or "admin", cred["password"], http_port,
                        connector_id or _conector(host))
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _data(valor: str, campo: str) -> datetime:
    try:
        return datetime.strptime(str(valor).replace("T", " ")[:19], FMT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{campo} invalido; use AAAA-MM-DD HH:MM:SS") from exc


@router.get("/diagnostico")
def api_driver_diagnostico(host: str, http_port: int = 80, connector_id: str = "") -> Dict[str, Any]:
    """O que falta para o gravador ser investigavel. Nao escreve nada."""
    g = _abrir(host, http_port, connector_id)
    try:
        return g.diagnostico()
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class PadronizarRequest(BaseModel):
    host: str
    http_port: int = Field(default=80, ge=1, le=65535)
    connector_id: str = ""
    # Subconjunto opcional das chaves do diagnostico. O VALOR novo nunca vem do
    # navegador: e recalculado aqui a partir do perfil.
    chaves: List[str] = Field(default_factory=list)


@router.post("/padronizar")
def api_driver_padronizar(req: PadronizarRequest) -> Dict[str, Any]:
    g = _abrir(req.host, req.http_port, req.connector_id)
    try:
        diag = g.diagnostico()
        mudancas = diag["mudancas"]
        if req.chaves:
            pedidas = set(req.chaves)
            mudancas = [m for m in mudancas if m["chave"] in pedidas]
        resultado = g.aplicar(mudancas, backup_dir=tenant_scoped_path("gravador_backups"))
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    resultado["alertas"] = diag["alertas"]
    resultado["mudancas"] = mudancas
    return resultado


@router.get("/indice")
def api_driver_indice(host: str, canal: int, inicio: str = "", fim: str = "",
                      http_port: int = 80, connector_id: str = "") -> Dict[str, Any]:
    """Linha do tempo de um canal: trechos gravados e quais tiveram movimento."""
    fim_dt = _data(fim, "fim") if fim else datetime.now()
    ini_dt = _data(inicio, "inicio") if inicio else fim_dt - timedelta(hours=24)
    if not (timedelta(0) < fim_dt - ini_dt <= timedelta(days=7)):
        raise HTTPException(status_code=400, detail="periodo precisa ser positivo e de ate 7 dias")
    g = _abrir(host, http_port, connector_id)
    try:
        segs = g.indice(int(canal), ini_dt, fim_dt)
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    def segundos(s) -> float:
        return (datetime.strptime(s.fim, FMT) - datetime.strptime(s.inicio, FMT)).total_seconds()

    return {
        "host": host, "canal": int(canal), "inicio": ini_dt.strftime(FMT), "fim": fim_dt.strftime(FMT),
        "segmentos": [s.__dict__ for s in segs],
        "resumo": {
            "arquivos": len(segs),
            "movimento_s": int(sum(segundos(s) for s in segs if s.tipo == "movimento")),
            "gravado_s": int(sum(segundos(s) for s in segs)),
        },
    }


@router.get("/relogio")
def api_driver_relogio(host: str, http_port: int = 80, connector_id: str = "") -> Dict[str, Any]:
    g = _abrir(host, http_port, connector_id)
    try:
        return g.relogio()
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
