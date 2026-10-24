"""Links dos provedores do rack: coleta na switch (API do RouterOS, so leitura)
e entrega ao monitoramento -> Zabbix.

Cada provedor cadastrado no rack (mapa_rack: porta de entrada + VLANs) vira
uma entidade "link" do monitoramento: no ar / caido / sem leitura, trafego de
entrada e saida (bit/s entre duas leituras), erros e a potencia optica do SFP.
O sync do Zabbix ja empurra o que esta em monitoring_entities.

A switch e lida pelo IP VIRTUAL do conector (connector_routing_vnat): o IP real
da VLAN de gerencia so responde por la. Usuario e senha de leitura ficam
criptografados no json_state do cliente, fora do meta da camada (o meta vai
inteiro para a tela).

Falha de leitura (switch sem resposta, login recusado) deixa o link "sem
leitura" -- nunca "caido": um problema no caminho da coleta nao pode virar
alarme de provedor fora.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.crypto import decrypt, encrypt
from app.core.tenant_context import get_current_tenant_slug, tenant_scoped_key
from app.services import db_store
from app.services.routeros_api import LeitorRouterOS, RouterOSErro

CHAVE_CRED = "rack_coleta_cred"
TIPOS_COM_COLETA = ("switch", "borda")

# Ultima leitura dos contadores, para o bit/s. A chave comeca pelo cliente.
_ULTIMO: Dict[Tuple[str, str, str, str, str], Tuple[float, int, int, int]] = {}
_LOCK = threading.Lock()


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tenant() -> str:
    return get_current_tenant_slug() or "default"


# ------------------------------------------------------------------ credencial

def _creds() -> Dict[str, Any]:
    dados = db_store.get_json_state(tenant_scoped_key(CHAVE_CRED), {}) or {}
    return dados if isinstance(dados, dict) else {}


def _chave_eq(layer_id: str, rack_id: str, eq_id: str) -> str:
    return f"{layer_id}|{rack_id}|{eq_id}"


def _alvo(coleta: Dict[str, Any]) -> str:
    """Para onde a senha pode ir: IP, porta e conector do momento em que o admin
    a guardou. Mudou qualquer um (um operador pode editar o rack), a senha deixa
    de ser usada ate o admin guardar de novo -- senao trocar o IP levaria a
    senha para um equipamento qualquer."""
    return f"{str(coleta.get('ip') or '').strip()}:{int(coleta.get('porta') or 8728)}@{str(coleta.get('conector') or '').strip()}"


def salvar_credencial(layer_id: str, rack_id: str, eq_id: str, usuario: str, senha: str,
                      coleta: Dict[str, Any]) -> Dict[str, Any]:
    usuario = str(usuario or "").strip()[:64]
    if not usuario or not senha:
        raise ValueError("Informe usuário e senha de leitura.")
    if not (coleta or {}).get("ip") or not (coleta or {}).get("conector"):
        raise ValueError("Salve antes o IP de gerência e o conector do equipamento.")
    dados = _creds()
    dados[_chave_eq(layer_id, rack_id, eq_id)] = {"usuario": usuario, "senha": encrypt(str(senha)),
                                                  "alvo": _alvo(coleta), "em": _agora()}
    res = db_store.set_json_state(tenant_scoped_key(CHAVE_CRED), dados)
    if not res.get("ok"):
        raise RuntimeError("Não foi possível guardar a senha agora. Tente de novo.")
    return {"ok": True}


def tem_credencial(layer_id: str, rack_id: str, eq_id: str, coleta: Dict[str, Any]) -> bool:
    """Senha guardada E ainda valida para o IP/porta/conector atual."""
    c = _creds().get(_chave_eq(layer_id, rack_id, eq_id))
    return isinstance(c, dict) and c.get("alvo") == _alvo(coleta or {})


def _credencial(layer_id: str, rack_id: str, eq_id: str, coleta: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    c = _creds().get(_chave_eq(layer_id, rack_id, eq_id))
    if not isinstance(c, dict) or not c.get("usuario"):
        return None
    if c.get("alvo") != _alvo(coleta):
        raise RouterOSErro("o IP, a porta ou o conector mudou depois que a senha foi guardada: o admin precisa guardar a senha de novo")
    try:
        return c["usuario"], decrypt(c.get("senha") or "")
    except Exception:
        return None


# ------------------------------------------------------------------ leitura

def _destino(coleta: Dict[str, Any]) -> Tuple[str, int]:
    """So pelo IP VIRTUAL do conector do cliente. IP real nunca: ele pode ser de
    outro cliente, e a coleta manda usuario e senha a cada minuto sem ninguem
    olhando (em 14/10/2026 a senha de gravador da Mega Alarmes foi parar num
    equipamento qualquer assim). Mesma regra de camera_senha_lote._alcance."""
    from app.services import connector_routing_vnat as vnat

    ip = str(coleta.get("ip") or "").strip()
    ipaddress.ip_address(ip)
    conector = str(coleta.get("conector") or "").strip()
    if not conector:
        raise RouterOSErro("escolha o conector por onde a switch é alcançada")
    if not vnat.has_mapping(conector):
        raise RouterOSErro("o conector não tem rede isolada mapeada: a leitura só sai pelo IP virtual")
    virtual = vnat.virtual_ip_for(conector, ip)
    if not virtual or virtual == vnat.IP_BLOQUEADO:
        raise RouterOSErro("conector não pertence a este cliente")
    if virtual == ip:
        raise RouterOSErro(f"o IP {ip} está fora das redes do conector: a leitura só sai pelo IP virtual")
    return virtual, int(coleta.get("porta") or 8728)


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace("dBm", "").strip())
    except (TypeError, ValueError):
        return None


def ler_switch(layer_id: str, rack_id: str, eq: Dict[str, Any], portas: List[str]) -> Dict[str, Any]:
    """Le identidade, contadores e SFP das portas pedidas. Nao grava nada."""
    coleta = eq.get("coleta") or {}
    try:
        cred = _credencial(layer_id, rack_id, eq["id"], coleta)
        if not cred:
            return {"ok": False, "erro": "sem usuário/senha de leitura cadastrados"}
        host, porta = _destino(coleta)
    except ValueError:
        return {"ok": False, "erro": "IP de gerência inválido"}
    except RouterOSErro as exc:
        return {"ok": False, "erro": str(exc)}
    try:
        with LeitorRouterOS(host, porta, cred[0], cred[1]) as r:
            ident = (r.ler("/system/identity/print") or [{}])[0].get("name", "")
            ifs = {i.get("name", ""): i for i in r.ler("/interface/print")}
            monit: Dict[str, Dict[str, str]] = {}
            fisicas = [p for p in portas if ifs.get(p, {}).get("type") == "ether"]
            if fisicas:
                for m in r.ler("/interface/ethernet/monitor", f"=numbers={','.join(fisicas)}", "=once="):
                    monit[m.get("name", "")] = m
    except RouterOSErro as exc:
        return {"ok": False, "erro": str(exc)}
    agora = time.time()
    tenant = _tenant()
    saida: Dict[str, Dict[str, Any]] = {}
    for p in portas:
        i = ifs.get(p)
        if not i:
            saida[p] = {"existe": False}
            continue
        rx, tx = int(i.get("rx-byte") or 0), int(i.get("tx-byte") or 0)
        err = int(i.get("rx-error") or 0) + int(i.get("tx-error") or 0)
        chave = (tenant, layer_id, rack_id, eq["id"], p)
        with _LOCK:
            antes = _ULTIMO.get(chave)
            _ULTIMO[chave] = (agora, rx, tx, err)
        in_bps = out_bps = erros = None
        if antes and agora > antes[0] and rx >= antes[1] and tx >= antes[2]:
            dt = agora - antes[0]
            in_bps, out_bps = round((rx - antes[1]) * 8 / dt), round((tx - antes[2]) * 8 / dt)
            erros = max(0, err - antes[3])
        m = monit.get(p, {})
        saida[p] = {
            "existe": True,
            "running": str(i.get("running")).lower() == "true",
            "disabled": str(i.get("disabled")).lower() == "true",
            "comentario": i.get("comment", ""),
            "in_bps": in_bps, "out_bps": out_bps, "erros": erros,
            "rate": m.get("rate", ""),
            "sfp_rx_dbm": _num(m.get("sfp-rx-power")),
            "sfp_tx_dbm": _num(m.get("sfp-tx-power")),
            "sfp_presente": m.get("sfp-module-present", ""),
        }
    return {"ok": True, "identidade": ident, "portas": saida, "lido_em": _agora()}


# ------------------------------------------------------------------ coleta do cliente

def _camadas_com_rack() -> List[Tuple[str, Dict[str, Any]]]:
    from app.api.endpoints import tools

    out = []
    for meta_path in tools._kmz_layers_dir().glob("*.meta.json"):
        meta = tools._read_kmz_layer_meta(meta_path)
        racks = meta.get("racks") if isinstance(meta.get("racks"), dict) else {}
        if racks:
            out.append((str(meta.get("id") or meta_path.name.replace(".meta.json", "")), meta))
    return out


def porta_lida(rack: Dict[str, Any], pv: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], str]]:
    """Onde o link do provedor e medido: a porta de entrada, se ja for de uma
    switch/borda; senao, segue a ligacao (provedor entra na DIO P1 e a DIO P1
    esta ligada na sfp4 da switch -> mede a sfp4). Sem switch no caminho: None."""
    from app.services.mapa_rack import caminho_da_porta

    eqs = {e["id"]: e for e in rack.get("equipamentos", [])}
    for passo in caminho_da_porta(rack, pv["entrada"]["eq"], pv["entrada"]["porta"]):
        eq = eqs.get(passo["eq"])
        if eq and eq.get("tipo") in TIPOS_COM_COLETA:
            return eq, passo["porta"]
    return None


def _sites_dos_conectores() -> Dict[str, str]:
    """Local de cada conector do cliente (o link herda: os grupos e o Telegram
    do Zabbix sao por local, e o rack tem nome proprio)."""
    tenant = _tenant()
    with db_store._conn() as c:
        return {str(dict(r)["entity_id"]): str(dict(r)["site"] or "") for r in c.execute(
            "SELECT entity_id, site FROM monitoring_entities WHERE tenant_slug=? AND entity_type='connector'", (tenant,)).fetchall()}


def _linha_do_link(layer_id: str, rack: Dict[str, Any], eq: Dict[str, Any], pv: Dict[str, Any],
                   leitura: Dict[str, Any], porta: str, site: str) -> Dict[str, Any]:
    p = (leitura.get("portas") or {}).get(porta) if leitura.get("ok") else None
    if not leitura.get("ok"):
        status, erro = "unknown", leitura.get("erro", "")
    elif not p or not p.get("existe"):
        status, erro = "unknown", f"porta {porta} não existe na switch"
    else:
        status, erro = ("up" if p["running"] and not p["disabled"] else "down"), ""
    banda = int(pv.get("banda_mbps") or 0)
    detalhe = {
        "provedor": pv["nome"], "rack": rack.get("nome", ""), "rack_id": rack["id"], "layer_id": layer_id,
        "equipamento": eq.get("nome", ""), "porta": porta, "entrada": pv["entrada"], "vlans": pv.get("vlans", []), "banda_mbps": banda,
        "erro": erro, "lido_em": leitura.get("lido_em", ""),
    }
    if p and p.get("existe"):
        detalhe.update({
            "link_in_bps": p["in_bps"], "link_out_bps": p["out_bps"], "link_erros": p["erros"],
            "sfp_rx_dbm": p["sfp_rx_dbm"], "sfp_tx_dbm": p["sfp_tx_dbm"], "rate": p["rate"],
            "comentario_porta": p["comentario"],
        })
        if banda and p["in_bps"] is not None:
            detalhe["uso_pct"] = round(max(p["in_bps"], p["out_bps"] or 0) / (banda * 1_000_000) * 100, 1)
    return {
        "entity_key": f"link:{rack['id']}:{pv['id']}", "entity_type": "link", "entity_id": pv["id"],
        "parent_key": f"rack:{rack['id']}", "site": site or rack.get("nome", ""),
        "connector_id": (eq.get("coleta") or {}).get("conector", ""),
        "display_name": f"LINK {pv['nome']} - {rack.get('nome', '')}", "status": status, "detail": detalhe,
    }


def coletar_cliente() -> Dict[str, Any]:
    """Uma passada no cliente atual: le as switches e grava as entidades link."""
    from app.services.monitoring_service import _observe_many

    linhas: List[Dict[str, Any]] = []
    lidas, falhas = 0, []
    sites = None
    for layer_id, meta in _camadas_com_rack():
        for rack in meta["racks"].values():
            eqs = {e["id"]: e for e in rack.get("equipamentos", [])}
            por_eq: Dict[str, List[Tuple[Dict[str, Any], str]]] = {}
            for pv in rack.get("provedores", []):
                alvo = porta_lida(rack, pv)
                if alvo and (alvo[0].get("coleta") or {}).get("ativo"):
                    por_eq.setdefault(alvo[0]["id"], []).append((pv, alvo[1]))
            if por_eq and sites is None:
                sites = _sites_dos_conectores()
            for eq_id, provs in por_eq.items():
                eq = eqs[eq_id]
                leitura = ler_switch(layer_id, rack["id"], eq, sorted({porta for _, porta in provs}))
                lidas += 1
                if not leitura.get("ok"):
                    falhas.append(f"{rack.get('nome')}/{eq.get('nome')}: {leitura.get('erro')}")
                site = (sites or {}).get((eq.get("coleta") or {}).get("conector", ""), "")
                linhas.extend(_linha_do_link(layer_id, rack, eq, pv, leitura, porta, site) for pv, porta in provs)
    # prune por tipo: provedor tirado do rack (ou coleta desligada) sai do monitoramento
    _observe_many(linhas, prune_entity_type="link")
    return {"switches": lidas, "links": len(linhas), "falhas": falhas}


def links_do_rack(rack_id: str) -> List[Dict[str, Any]]:
    import json

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


def testar(layer_id: str, rack: Dict[str, Any], eq_id: str) -> Dict[str, Any]:
    eq = next((e for e in rack.get("equipamentos", []) if e["id"] == eq_id), None)
    if not eq:
        raise LookupError("Equipamento não encontrado.")
    portas = sorted({a[1] for a in (porta_lida(rack, pv) for pv in rack.get("provedores", [])) if a and a[0]["id"] == eq_id})
    return ler_switch(layer_id, rack["id"], eq, portas)
