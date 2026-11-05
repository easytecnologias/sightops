from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.core.tenant_context import get_current_tenant_slug
from app.services import automacao_acoes, automacao_store

# Automacoes (acionam equipamento vivo do cliente): escrita so de admin, em
# security._role_rules. Modulo "termico" em permissions.
router = APIRouter(prefix="/api/automacoes", tags=["automacoes"])


def _executar(fn, *args) -> Any:
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
def api_automacoes_listar() -> Dict[str, Any]:
    return _executar(automacao_store.listar)


@router.post("")
def api_automacoes_criar(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(automacao_store.salvar, payload)


@router.put("/{regra_id}")
def api_automacoes_salvar(regra_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(automacao_store.salvar, payload, regra_id)


@router.delete("/{regra_id}")
def api_automacoes_excluir(regra_id: str) -> Dict[str, Any]:
    return _executar(automacao_store.excluir, regra_id)


@router.post("/{regra_id}/testar")
def api_automacoes_testar(regra_id: str) -> Dict[str, Any]:
    """Roda agora, no modo da regra (em 'valer' aciona o equipamento de verdade)."""
    regra = _executar(automacao_store.obter, regra_id)
    automacao_acoes.rodar_regra(get_current_tenant_slug(), regra)
    return _executar(automacao_store.listar)
