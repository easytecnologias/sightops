from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.services import switch_provedores

# Switch Provedores (menu Redes): switches da rede neutra lidas pela API do
# RouterOS, so leitura. Sob /api/switch (modulo "Switches e rede"); POST como
# operador (security._role_rules), DELETE so admin pela regra de exclusao.
router = APIRouter(prefix="/api/switch/provedores", tags=["switch"])


def _executar(fn, *args) -> Dict[str, Any]:
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("")
def api_switch_provedores_listar() -> Dict[str, Any]:
    return {"ok": True, "switches": switch_provedores.listar()}


@router.post("")
def api_switch_provedores_salvar(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(switch_provedores.salvar, payload)


@router.post("/{sw_id}/testar")
def api_switch_provedores_testar(sw_id: str) -> Dict[str, Any]:
    return {"ok": True, **_executar(switch_provedores.testar, sw_id)}


@router.delete("/{sw_id}")
def api_switch_provedores_excluir(sw_id: str) -> Dict[str, Any]:
    return _executar(switch_provedores.excluir, sw_id)
