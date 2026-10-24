"""Switch Provedores (menu Redes): cadastro das switches da rede neutra
(MikroTik CRS) e a leitura delas a cada minuto.

Uma leitura por switch serve a tudo: a tela (portas com comentario, link,
velocidade, trafego e sinal do SFP), a entidade "switch_provedor" do
monitoramento (vai ao Zabbix) e os links dos provedores dos racks
(rack_links.py), que apontam para a switch cadastrada.

Regras que custaram caro em outros modulos:
- so pelo IP VIRTUAL do conector mapeado: o IP real pode ser de outro cliente
  e a coleta manda usuario e senha a cada minuto (camera_senha_lote._alcance);
- a senha e apagada quando IP, porta ou conector mudam sem senha nova;
- falha de leitura deixa os links "sem leitura", nunca "caidos".
"""
from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.crypto import decrypt, encrypt
from app.core.tenant_context import get_current_tenant_slug
from app.services import db_store
from app.services.routeros_api import LeitorRouterOS, RouterOSErro

ENTIDADE = "switch_provedor"
# Contadores da ultima leitura, para o bit/s. A chave comeca pelo cliente.
_ULTIMO: Dict[Tuple[str, str, str], Tuple[float, int, int, int]] = {}
_LOCK = threading.Lock()


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tenant() -> str:
    return get_current_tenant_slug() or "default"


def _txt(v: Any, n: int) -> str:
    return str(v or "").strip()[:n]


def _rows(c: Any, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, params).fetchall()]


def _publico(r: Dict[str, Any]) -> Dict[str, Any]:
    """Linha para a tela: sem a senha, com a leitura ja aberta."""
    out = {k: v for k, v in r.items() if k not in ("senha_enc", "tenant_slug")}
    out["tem_senha"] = bool(r.get("senha_enc"))
    try:
        out["leitura"] = json.loads(r.get("ultima_leitura") or "{}")
    except Exception:
        out["leitura"] = {}
    out.pop("ultima_leitura", None)
    return out


# ------------------------------------------------------------------ alcance

def destino(connector_id: str, ip: str) -> str:
    """IP virtual do conector para o IP de gerencia. Recusa tudo que daria o IP real."""
    from app.services import connector_routing_vnat as vnat

    ipaddress.ip_address(ip)
    if not connector_id:
        raise RouterOSErro("escolha o conector por onde a switch é alcançada")
    if not vnat.has_mapping(connector_id):
        raise RouterOSErro("o conector não tem rede isolada mapeada: a leitura só sai pelo IP virtual")
    virtual = vnat.virtual_ip_for(connector_id, ip)
    if not virtual or virtual == vnat.IP_BLOQUEADO:
        raise RouterOSErro("conector não pertence a este cliente")
    if virtual == ip:
        raise RouterOSErro(f"o IP {ip} está fora das redes do conector: a leitura só sai pelo IP virtual")
    return virtual


# ------------------------------------------------------------------ cadastro

def listar() -> List[Dict[str, Any]]:
    with db_store._conn() as c:
        return [_publico(r) for r in _rows(c, "SELECT * FROM provider_switches WHERE tenant_slug=? ORDER BY nome", (_tenant(),))]


def obter(sw_id: str) -> Optional[Dict[str, Any]]:
    with db_store._conn() as c:
        r = c.execute("SELECT * FROM provider_switches WHERE tenant_slug=? AND id=?", (_tenant(), _txt(sw_id, 40))).fetchone()
    return dict(r) if r else None


def salvar(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    sw_id = _txt(payload.get("id"), 40)
    nome = _txt(payload.get("nome"), 80)
    if not nome:
        raise ValueError("Informe o nome da switch.")
    ip = _txt(payload.get("ip"), 45)
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError("IP de gerência inválido.")
    try:
        porta = int(payload.get("porta") or 8728)
    except (TypeError, ValueError):
        raise ValueError("Porta da API inválida.")
    if not 1 <= porta <= 65535:
        raise ValueError("Porta da API inválida.")
    conector = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("connector_id") or ""))[:40]
    try:
        destino(conector, ip)   # recusa ja no cadastro o que nunca poderia ser lido
    except RouterOSErro as exc:
        raise ValueError(str(exc)[:1].upper() + str(exc)[1:] + ".")
    usuario = _txt(payload.get("usuario"), 64)
    senha = str(payload.get("senha") or "")
    ativo = 0 if str(payload.get("ativo")).lower() in ("0", "false", "nao", "não") else 1
    agora = _agora()
    with db_store._conn() as c:
        atual = None
        if sw_id:
            r = c.execute("SELECT * FROM provider_switches WHERE tenant_slug=? AND id=?", (tenant, sw_id)).fetchone()
            if not r:
                raise LookupError("Switch não encontrada.")
            atual = dict(r)
        dup = c.execute("SELECT nome FROM provider_switches WHERE tenant_slug=? AND connector_id=? AND ip=? AND id<>?",
                        (tenant, conector, ip, sw_id)).fetchone()
        if dup:
            raise ValueError(f"Este IP já está cadastrado ({dict(dup)['nome']}).")
        if senha:
            if not usuario:
                raise ValueError("Informe o usuário junto com a senha.")
            senha_enc = encrypt(senha)
        elif atual and (atual["ip"], int(atual["porta"]), atual["connector_id"]) == (ip, porta, conector) and usuario == atual["usuario"]:
            senha_enc = atual["senha_enc"]
        else:
            # destino ou usuario mudou sem senha nova: a guardada nao vai junto
            senha_enc = ""
        if not senha_enc and ativo and not atual:
            raise ValueError("Informe usuário e senha de leitura.")
        valores = (nome, _txt(payload.get("site"), 80), ip, porta, conector, usuario, senha_enc, ativo, agora)
        if atual:
            c.execute("UPDATE provider_switches SET nome=?, site=?, ip=?, porta=?, connector_id=?, usuario=?, senha_enc=?, ativo=?, "
                      "updated_at=? WHERE tenant_slug=? AND id=?", (*valores, tenant, sw_id))
        else:
            sw_id = f"sw{uuid.uuid4().hex[:10]}"
            c.execute("INSERT INTO provider_switches(nome, site, ip, porta, connector_id, usuario, senha_enc, ativo, updated_at, "
                      "id, tenant_slug, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (*valores, sw_id, tenant, agora))
    return {"ok": True, "id": sw_id, "senha_mantida": bool(senha_enc), "precisa_senha": not senha_enc}


def excluir(sw_id: str) -> Dict[str, Any]:
    from app.services.rack_links import racks_que_usam

    if not obter(sw_id):
        raise LookupError("Switch não encontrada.")
    usados = racks_que_usam(sw_id)
    if usados:
        raise ValueError(f"Em uso no rack {', '.join(usados)}. Tire a switch do rack antes.")
    with db_store._conn() as c:
        c.execute("DELETE FROM provider_switches WHERE tenant_slug=? AND id=?", (_tenant(), sw_id))
        c.execute("DELETE FROM monitoring_entities WHERE tenant_slug=? AND entity_key=?", (_tenant(), f"swprov:{sw_id}"))
    return {"ok": True}


# ------------------------------------------------------------------ leitura

def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace("dBm", "").strip())
    except (TypeError, ValueError):
        return None


def ler(sw: Dict[str, Any]) -> Dict[str, Any]:
    """Le identidade, modelo e TODAS as portas fisicas. Nao grava nada."""
    if not sw.get("senha_enc") or not sw.get("usuario"):
        return {"ok": False, "erro": "sem usuário/senha de leitura (guarde a senha de novo se mudou IP, porta ou conector)"}
    try:
        host = destino(sw["connector_id"], sw["ip"])
        senha = decrypt(sw["senha_enc"])
    except RouterOSErro as exc:
        return {"ok": False, "erro": str(exc)}
    except Exception:
        return {"ok": False, "erro": "não foi possível abrir a senha guardada: guarde de novo"}
    try:
        with LeitorRouterOS(host, int(sw.get("porta") or 8728), sw["usuario"], senha) as r:
            ident = (r.ler("/system/identity/print") or [{}])[0].get("name", "")
            rb = (r.ler("/system/routerboard/print") or [{}])[0]
            res = (r.ler("/system/resource/print") or [{}])[0]
            ifs = [i for i in r.ler("/interface/print") if i.get("type") == "ether"]
            sfps = [i["name"] for i in ifs if "sfp" in i.get("name", "")]
            monit = {m.get("name", ""): m for m in (r.ler("/interface/ethernet/monitor", f"=numbers={','.join(sfps)}", "=once=") if sfps else [])}
    except RouterOSErro as exc:
        return {"ok": False, "erro": str(exc)}
    agora = time.time()
    tenant = _tenant()
    portas = []
    for i in ifs:
        nome = i.get("name", "")
        rx, tx = int(i.get("rx-byte") or 0), int(i.get("tx-byte") or 0)
        err = int(i.get("rx-error") or 0) + int(i.get("tx-error") or 0)
        chave = (tenant, sw["id"], nome)
        with _LOCK:
            antes = _ULTIMO.get(chave)
            _ULTIMO[chave] = (agora, rx, tx, err)
        in_bps = out_bps = erros = None
        if antes and agora > antes[0] and rx >= antes[1] and tx >= antes[2]:
            dt = agora - antes[0]
            in_bps, out_bps = round((rx - antes[1]) * 8 / dt), round((tx - antes[2]) * 8 / dt)
            erros = max(0, err - antes[3])
        m = monit.get(nome, {})
        portas.append({
            "nome": nome, "comentario": i.get("comment", ""),
            "running": str(i.get("running")).lower() == "true", "disabled": str(i.get("disabled")).lower() == "true",
            "in_bps": in_bps, "out_bps": out_bps, "erros": erros, "rate": m.get("rate", ""),
            "sfp_presente": m.get("sfp-module-present", ""), "sfp_rx_dbm": _num(m.get("sfp-rx-power")),
            "sfp_tx_dbm": _num(m.get("sfp-tx-power")), "sfp_modelo": m.get("sfp-vendor-part-number", ""),
        })
    return {"ok": True, "identidade": ident, "modelo": rb.get("model", "") or res.get("board-name", ""),
            "versao": res.get("version", ""), "uptime": res.get("uptime", ""), "portas": portas, "lido_em": _agora()}


def testar(sw_id: str) -> Dict[str, Any]:
    sw = obter(sw_id)
    if not sw:
        raise LookupError("Switch não encontrada.")
    leitura = ler(sw)
    _gravar_leitura(_tenant(), sw["id"], leitura)
    return leitura


def _gravar_leitura(tenant: str, sw_id: str, leitura: Dict[str, Any]) -> None:
    with db_store._conn() as c:
        if leitura.get("ok"):
            c.execute("UPDATE provider_switches SET ultima_leitura=?, lido_em=?, erro='' WHERE tenant_slug=? AND id=?",
                      (json.dumps(leitura, ensure_ascii=False), leitura["lido_em"], tenant, sw_id))
        else:
            c.execute("UPDATE provider_switches SET erro=? WHERE tenant_slug=? AND id=?", (leitura.get("erro", "")[:300], tenant, sw_id))


def coletar_cliente() -> Dict[str, Any]:
    """Uma passada no cliente atual: le as switches ativas, grava a leitura e
    as entidades (switch e links dos provedores dos racks)."""
    from app.services.monitoring_service import _observe_many
    from app.services import rack_links

    tenant = _tenant()
    with db_store._conn() as c:
        sws = _rows(c, "SELECT * FROM provider_switches WHERE tenant_slug=? AND ativo=1", (tenant,))
        # sem local no cadastro: o do conector. Os grupos e o Telegram do Zabbix
        # sao por local; vazio, o alerta da switch e dos links nao saia.
        sites = {str(r["entity_id"]): str(r["site"] or "") for r in _rows(
            c, "SELECT entity_id, site FROM monitoring_entities WHERE tenant_slug=? AND entity_type='connector'", (tenant,))}
    for sw in sws:
        sw["site"] = sw.get("site") or sites.get(sw["connector_id"], "")
    leituras: Dict[str, Dict[str, Any]] = {}
    entidades, falhas = [], []
    for sw in sws:
        leitura = ler(sw)
        leituras[sw["id"]] = leitura
        _gravar_leitura(tenant, sw["id"], leitura)
        if not leitura.get("ok"):
            falhas.append(f"{sw['nome']}: {leitura.get('erro')}")
        portas = leitura.get("portas") or []
        entidades.append({
            "entity_key": f"swprov:{sw['id']}", "entity_type": ENTIDADE, "entity_id": sw["id"], "site": sw.get("site", ""),
            "connector_id": sw["connector_id"], "display_name": sw["nome"],
            "status": "up" if leitura.get("ok") else "down",
            "detail": {"ip": sw["ip"], "modelo": leitura.get("modelo", ""), "versao": leitura.get("versao", ""),
                       "identidade": leitura.get("identidade", ""), "erro": leitura.get("erro", ""),
                       "ports_total": len(portas) if leitura.get("ok") else None,
                       "ports_up": sum(1 for p in portas if p["running"]) if leitura.get("ok") else None,
                       "lido_em": leitura.get("lido_em", "")},
        })
    _observe_many(entidades, prune_entity_type=ENTIDADE)
    links = rack_links.coletar_links(leituras, {sw["id"]: sw for sw in sws})
    return {"switches": len(sws), "links": links, "falhas": falhas}
