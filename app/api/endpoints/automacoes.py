from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.core.tenant_context import get_current_tenant_slug
from app.services import automacao_acoes, automacao_store

# Automacoes (acionam equipamento vivo do cliente): escrita so de admin, em
# security._role_rules. Modulo "termico" em permissions.
router = APIRouter(prefix="/api/automacoes", tags=["automacoes"])


def _rede(fn, *args) -> Any:
    """Fala com a speed: sem resposta dela vira aviso na tela, nao erro 500."""
    try:
        return _executar(fn, *args)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="A speed não respondeu.")


def _executar(fn, *args) -> Any:
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# Calibracao da speed (automacao Seguir o alarme). POST so admin, como o resto.
@router.get("/speed/posicao")
def api_speed_posicao(ip: str, connector_id: str = "") -> Dict[str, Any]:
    return _rede(automacao_acoes.posicao_speed, ip, connector_id)


@router.post("/speed/mover")
def api_speed_mover(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _rede(automacao_acoes.mover_speed, str(payload.get("ip") or ""), str(payload.get("connector_id") or ""),
                 int(payload.get("pan") or 0), int(payload.get("tilt") or 0), int(payload.get("zoom") or 0))


@router.post("/speed/vivo")
def api_speed_vivo(payload: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import termico_store

    ip, conector = str(payload.get("ip") or ""), str(payload.get("connector_id") or "")
    _rede(automacao_acoes._speed_do_usuario, ip, conector)      # so speed, nunca outra camera
    return _rede(lambda: termico_store.abrir_vivo(ip, conector, "colorida", True, True))


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
