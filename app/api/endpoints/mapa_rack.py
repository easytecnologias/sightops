from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.services import rack_links

# Leitura automatica dos links do rack (app/services/rack_links.py). Fica sob
# /api/mapa (modulo Mapa). Gravar a senha: so admin (security._role_rules);
# testar a leitura: operador.
router = APIRouter(prefix="/api/mapa/rack", tags=["mapa"])


def _rack(layer_id: str, rack_id: str) -> Dict[str, Any]:
    from app.api.endpoints import tools

    meta, _ = tools._meta_da_camada_ou_404(str(layer_id or ""))
    rack = (meta.get("racks") or {}).get(str(rack_id or ""))
    if not rack:
        raise HTTPException(404, "Rack não encontrado.")
    return rack


def _eq(rack: Dict[str, Any], eq_id: str) -> Dict[str, Any]:
    eq = next((e for e in rack.get("equipamentos", []) if e.get("id") == eq_id), None)
    if not eq:
        raise HTTPException(404, "Equipamento não encontrado no rack.")
    if eq.get("tipo") not in rack_links.TIPOS_COM_COLETA:
        raise HTTPException(400, "Leitura automática só para switch e borda.")
    return eq


@router.get("/coleta")
def api_rack_coleta(layer_id: str, rack_id: str) -> Dict[str, Any]:
    rack = _rack(layer_id, rack_id)
    credenciais = {e["id"]: rack_links.tem_credencial(layer_id, rack_id, e["id"], e.get("coleta") or {})
                   for e in rack.get("equipamentos", []) if e.get("tipo") in rack_links.TIPOS_COM_COLETA}
    return {"ok": True, "links": rack_links.links_do_rack(rack_id), "credenciais": credenciais}


@router.post("/credencial")
def api_rack_credencial(payload: Dict[str, Any]) -> Dict[str, Any]:
    layer_id, rack_id, eq_id = (str(payload.get(k) or "") for k in ("layer_id", "rack_id", "eq_id"))
    eq = _eq(_rack(layer_id, rack_id), eq_id)
    try:
        # a senha fica presa ao IP/porta/conector GRAVADOS no rack agora
        return rack_links.salvar_credencial(layer_id, rack_id, eq_id, payload.get("usuario"), payload.get("senha"),
                                            eq.get("coleta") or {})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@router.post("/testar")
def api_rack_testar(payload: Dict[str, Any]) -> Dict[str, Any]:
    layer_id, rack_id, eq_id = (str(payload.get(k) or "") for k in ("layer_id", "rack_id", "eq_id"))
    rack = _rack(layer_id, rack_id)
    _eq(rack, eq_id)
    return {"ok": True, **rack_links.testar(layer_id, rack, eq_id)}
