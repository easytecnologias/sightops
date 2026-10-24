"""Links dos provedores do rack -> monitoramento -> Zabbix.

Cada provedor cadastrado no rack (mapa_rack: porta de entrada + VLANs) vira
uma entidade "link": no ar / caido / sem leitura, trafego, erros e potencia do
SFP. Os numeros vem da leitura da switch cadastrada em Switch Provedores
(switch_provedores.py): o equipamento "switch" do rack aponta para ela
(switch_id) e a coleta da switch, a cada minuto, chama coletar_links().

Provedor que entra na DIO e medido na porta da switch ligada a ela.
Falha de leitura deixa o link "sem leitura" -- nunca "caido": problema no
caminho da coleta nao pode virar alarme de provedor fora.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.core.tenant_context import get_current_tenant_slug
from app.services import db_store


def _tenant() -> str:
    return get_current_tenant_slug() or "default"


def _camadas_com_rack() -> List[Tuple[str, Dict[str, Any]]]:
    from app.api.endpoints import tools

    out = []
    for meta_path in tools._kmz_layers_dir().glob("*.meta.json"):
        meta = tools._read_kmz_layer_meta(meta_path)
        racks = meta.get("racks") if isinstance(meta.get("racks"), dict) else {}
        if racks:
            out.append((str(meta.get("id") or meta_path.name.replace(".meta.json", "")), meta))
    return out


def racks_que_usam(sw_id: str) -> List[str]:
    return sorted({rack.get("nome", "?") for _, meta in _camadas_com_rack() for rack in meta["racks"].values()
                   if any(e.get("switch_id") == sw_id for e in rack.get("equipamentos", []))})


def porta_lida(rack: Dict[str, Any], pv: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], str]]:
    """Onde o link do provedor e medido: a porta de entrada, se ja for de uma
    switch cadastrada; senao, segue a ligacao (provedor na DIO P1, DIO P1 ligada
    na sfp4 da switch -> mede a sfp4). Sem switch cadastrada no caminho: None."""
    from app.services.mapa_rack import caminho_da_porta

    eqs = {e["id"]: e for e in rack.get("equipamentos", [])}
    for passo in caminho_da_porta(rack, pv["entrada"]["eq"], pv["entrada"]["porta"]):
        eq = eqs.get(passo["eq"])
        if eq and eq.get("switch_id"):
            return eq, passo["porta"]
    return None


def _linha(rack: Dict[str, Any], pv: Dict[str, Any], porta: str,
           sw: Dict[str, Any], leitura: Dict[str, Any]) -> Dict[str, Any]:
    p = next((x for x in (leitura.get("portas") or []) if x["nome"].lower() == porta.lower()), None) if leitura.get("ok") else None
    if not leitura.get("ok"):
        status, erro = "unknown", leitura.get("erro", "sem leitura da switch")
    elif not p:
        status, erro = "unknown", f"a porta {porta} não existe em {sw.get('nome')}"
    else:
        status, erro = ("up" if p["running"] and not p["disabled"] else "down"), ""
    banda = int(pv.get("banda_mbps") or 0)
    detalhe = {
        "provedor": pv["nome"], "rack": rack.get("nome", ""), "rack_id": rack["id"], "switch": sw.get("nome", ""),
        "switch_id": sw.get("id", ""), "porta": porta, "entrada": pv["entrada"], "vlans": pv.get("vlans", []),
        "banda_mbps": banda, "erro": erro, "lido_em": leitura.get("lido_em", ""),
    }
    if p:
        detalhe.update({"link_in_bps": p["in_bps"], "link_out_bps": p["out_bps"], "link_erros": p["erros"],
                        "sfp_rx_dbm": p["sfp_rx_dbm"], "sfp_tx_dbm": p["sfp_tx_dbm"], "rate": p["rate"],
                        "comentario_porta": p["comentario"]})
        if banda and p["in_bps"] is not None:
            detalhe["uso_pct"] = round(max(p["in_bps"], p["out_bps"] or 0) / (banda * 1_000_000) * 100, 1)
    return {
        "entity_key": f"link:{rack['id']}:{pv['id']}", "entity_type": "link", "entity_id": pv["id"],
        "parent_key": f"rack:{rack['id']}", "site": sw.get("site") or rack.get("nome", ""),
        "connector_id": sw.get("connector_id", ""),
        "display_name": f"LINK {pv['nome']} - {rack.get('nome', '')}", "status": status, "detail": detalhe,
    }


def coletar_links(leituras: Dict[str, Dict[str, Any]], switches: Dict[str, Dict[str, Any]]) -> int:
    """Grava as entidades link a partir das leituras das switches (ja feitas).
    So provedor que chega numa switch cadastrada E ativa vira link."""
    from app.services.monitoring_service import _observe_many

    linhas: List[Dict[str, Any]] = []
    for _, meta in _camadas_com_rack():
        for rack in meta["racks"].values():
            for pv in rack.get("provedores", []):
                alvo = porta_lida(rack, pv)
                if not alvo:
                    continue
                eq, porta = alvo
                sw = switches.get(eq["switch_id"])
                if not sw:
                    continue
                linhas.append(_linha(rack, pv, porta, sw, leituras.get(sw["id"]) or {}))
    # provedor tirado do rack, switch desligada ou removida: o link sai do monitoramento
    _observe_many(linhas, prune_entity_type="link")
    return len(linhas)


def links_do_rack(rack_id: str) -> List[Dict[str, Any]]:
    tenant = _tenant()
    with db_store._conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT entity_key, entity_id, status, last_checked_at, last_changed_at, detail_json FROM monitoring_entities "
            "WHERE tenant_slug=? AND entity_type='link' AND parent_key=?", (tenant, f"rack:{rack_id}")).fetchall()]
    for r in rows:
        try:
            r["detail"] = json.loads(r.pop("detail_json") or "{}")
        except Exception:
            r["detail"] = {}
    return rows
