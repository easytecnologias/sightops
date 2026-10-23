from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.services import rotas_cadastro, rotas_store

# Controle de Rotas (transporte escolar / PNATE). Escrita declarada em
# security._role_rules; DELETE vira so admin pela regra central de exclusao.
router = APIRouter(prefix="/api/rotas", tags=["rotas"])


def _executar(fn, *args) -> Dict[str, Any]:
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/frota")
def api_rotas_frota() -> Dict[str, Any]:
    return {"ok": True, **rotas_store.frota()}


@router.post("/operadores")
def api_rotas_salvar_operador(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(rotas_store.salvar_operador, payload)


@router.post("/veiculos")
def api_rotas_salvar_veiculo(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(rotas_store.salvar_veiculo, payload)


@router.post("/motoristas")
def api_rotas_salvar_motorista(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(rotas_store.salvar_motorista, payload)


@router.get("/cadastro")
def api_rotas_cadastro() -> Dict[str, Any]:
    return {"ok": True, **rotas_cadastro.cadastro()}


@router.post("/contratantes")
def api_rotas_salvar_contratante(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(rotas_cadastro.salvar_contratante, payload)


@router.post("/contratos")
def api_rotas_salvar_contrato(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(rotas_cadastro.salvar_contrato, payload)


@router.post("/escolas")
def api_rotas_salvar_escola(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(rotas_cadastro.salvar_escola, payload)


@router.post("/rotas")
def api_rotas_salvar_rota(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(rotas_cadastro.salvar_rota, payload)


@router.post("/alunos")
def api_rotas_salvar_aluno(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _executar(rotas_cadastro.salvar_aluno, payload)


@router.delete("/{tabela}/{item_id}")
def api_rotas_excluir(tabela: str, item_id: str) -> Dict[str, Any]:
    return _executar(rotas_store.excluir, tabela, item_id)
