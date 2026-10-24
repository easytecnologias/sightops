from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.services import rack_links, switch_provedores

# Links dos provedores do rack (app/services/rack_links.py), sob /api/mapa
# (modulo Mapa). So leitura: a senha da switch e cadastrada em Switch Provedores.
router = APIRouter(prefix="/api/mapa/rack", tags=["mapa"])


@router.get("/coleta")
def api_rack_coleta(layer_id: str, rack_id: str) -> Dict[str, Any]:
    from app.api.endpoints import tools

    meta, _ = tools._meta_da_camada_ou_404(str(layer_id or ""))
    if str(rack_id or "") not in (meta.get("racks") or {}):
        raise HTTPException(404, "Rack não encontrado.")
    # so o que o rack precisa da switch: nome, estado e as portas lidas
    switches = [{"id": s["id"], "nome": s["nome"], "site": s.get("site", ""), "ip": s["ip"], "ativo": s["ativo"],
                 "erro": s.get("erro", ""), "lido_em": s.get("lido_em", ""), "tem_senha": s["tem_senha"],
                 "modelo": (s.get("leitura") or {}).get("modelo", ""),
                 "portas": [{"nome": p["nome"], "comentario": p.get("comentario", ""), "running": p.get("running")}
                            for p in (s.get("leitura") or {}).get("portas", [])]}
                for s in switch_provedores.listar()]
    return {"ok": True, "links": rack_links.links_do_rack(rack_id), "switches": switches}
