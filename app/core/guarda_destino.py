"""Dependency unica para rota que abre conexao com equipamento pelo IP do pedido.

Roda ANTES do handler (FastAPI resolve as dependencias primeiro) e usa a mesma
regra de app.core.destino, pelo caminho que o pacote faz de fato: com a dica de
conector do corpo/query, senao o conector do gravador no inventario, senao o
_reach da camera. Gravador/camera do proprio cliente passa (LAN ou faixa virtual
do conector dele); faixa virtual alheia, rede interna e IP sem dono nao.
"""
from __future__ import annotations

import asyncio
import contextvars
import re
from typing import Any, Dict, List, Tuple

from fastapi import Request


# Conector que o pedido indicou, para o handler conectar pelo MESMO caminho que
# a guarda conferiu (rotas de gravador que nao leem connector_id do corpo).
_dica_do_pedido: contextvars.ContextVar[str] = contextvars.ContextVar("guarda_dica_do_pedido", default="")


def dica_do_pedido() -> str:
    return _dica_do_pedido.get()


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _conector_do_gravador(ip: str) -> str:
    # NVR e DVR tem inventarios separados: a rota de DVR resolve pelo dela.
    from app.api.endpoints import dvr, nvr
    return nvr._recorder_connector_for_host(ip) or dvr._recorder_connector_for_host(ip) or ""


def guarda_destino(*campos: str):
    """Depends(guarda_destino("ip")): confere o destino de cada campo presente
    (query ou corpo JSON). Campo ausente fica para a rota responder."""

    async def _dep(request: Request) -> None:
        dados: Dict[str, Any] = dict(request.query_params)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                corpo = await request.json()
            except Exception:
                corpo = None  # a propria rota responde o erro de payload
            if isinstance(corpo, dict):
                dados.update(corpo)
        dica = _texto(dados.get("connector_id") or dados.get("remote_connector_id"))
        _dica_do_pedido.set(dica)
        alvos: List[Tuple[str, str]] = []
        for campo in campos:
            ip = re.sub(r"^(\d+\.\d+\.\d+\.\d+):\d+$", r"\1", _texto(dados.get(campo)))  # IP:porta
            if ip:
                alvos.append((ip, dica or await asyncio.to_thread(_conector_do_gravador, ip)))
        if alvos:
            from app.api.endpoints.maintenance import _conferir_destinos
            await asyncio.to_thread(_conferir_destinos, alvos)

    return _dep
