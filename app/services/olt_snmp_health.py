"""Saude da propria OLT por SNMP, para o host dela no Zabbix.

A telemetria de ONU ja vai para o Zabbix ONU a ONU; o host da OLT so dizia
"esta no ar". Aqui entram os dados da OLT em si: tempo ligada, uplinks (link e
trafego) e PONs (link). Premissa vendida aos clientes: tudo no Zabbix.

Hoje so FiberHome AN5516, que publica o IF-MIB padrao com um esquema de
indices conhecido (medido na SIERRA em 07/10/2026):
    uplink  19/1..19/5  -> ifIndex n<<19            (524288, 1048576, ...)
    PON     slot/pon    -> ifIndex slot<<25 | pon<<19
    ONU     slot/pon/n  -> ifIndex slot<<25 | pon<<19 | n<<8
A tabela inteira passa de mil linhas e o agente responde ~10 GET/s -- por isso
NADA de walk completo: os indices sao calculados e lidos um a um (~45 GETs).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.services import connector_routing_vnat as _vnat
from app.services.snmp_client import GETNEXT_REQUEST, Snmp

logger = logging.getLogger("cam-snapshot")

STATE_KEY = "olt_snmp_health"
_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
_IF_OPER = "1.3.6.1.2.1.2.2.1.8"
_IF_HC_IN = "1.3.6.1.2.1.31.1.1.1.6"
_IF_HC_OUT = "1.3.6.1.2.1.31.1.1.1.10"
_IF_IN = "1.3.6.1.2.1.2.2.1.10"
_IF_OUT = "1.3.6.1.2.1.2.2.1.16"
_SLOT = 1 << 25
_PON = 1 << 19


def _e_fiberhome(olt: Dict[str, Any]) -> bool:
    texto = f"{olt.get('vendor') or ''} {olt.get('model') or ''}".lower()
    return "fiberhome" in texto or "an5516" in texto


def _get(s: Snmp, oid: str) -> Any:
    try:
        valor = s.get(oid)
    except Exception:
        return None
    return None if valor is None or "noSuch" in str(valor) else valor


def _proximo(s: Snmp, oid: str):
    try:
        erro, prox, valor = s._ask(oid, GETNEXT_REQUEST)
    except Exception:
        return None, None
    if erro or "endOfMib" in str(valor):
        return None, None
    return prox, valor


def _indice(oid: str, base: str) -> int | None:
    if not oid or not oid.startswith(base + "."):
        return None
    try:
        return int(oid[len(base) + 1:].split(".")[0])
    except ValueError:
        return None


def _contador(s: Snmp, hc: str, legado: str, idx: int) -> int | None:
    for base in (hc, legado):
        valor = _get(s, f"{base}.{idx}")
        try:
            return int(valor)
        except (TypeError, ValueError):
            continue
    return None


def coletar_saude_fiberhome(host: str, community: str) -> Dict[str, Any]:
    s = Snmp(host, community, timeout=4)
    ticks = _get(s, "1.3.6.1.2.1.1.3.0")
    if ticks is None:
        raise RuntimeError("a OLT nao respondeu SNMP (comunidade ou rota)")
    saude: Dict[str, Any] = {"uptime_days": round(int(ticks) / 100 / 86400, 2)}

    # Uplinks: os primeiros ifIndex, antes do primeiro slot de placa PON.
    uplinks: List[Dict[str, Any]] = []
    oid = _IF_DESCR
    for _ in range(32):
        oid, nome = _proximo(s, oid)
        idx = _indice(oid, _IF_DESCR)
        if idx is None or idx >= _SLOT:
            break
        oper = _get(s, f"{_IF_OPER}.{idx}")
        uplinks.append({
            "nome": str(nome), "up": str(oper) == "1",
            "in": _contador(s, _IF_HC_IN, _IF_IN, idx), "out": _contador(s, _IF_HC_OUT, _IF_OUT, idx),
        })
    saude["uplinks_total"] = len(uplinks)
    saude["uplinks_up"] = sum(1 for u in uplinks if u["up"])
    saude["uplinks"] = [{"nome": u["nome"], "up": u["up"]} for u in uplinks]
    # Contador somado de todos os uplinks; o Zabbix transforma em bits/s.
    if any(u["in"] is not None for u in uplinks):
        saude["uplink_in_octets"] = sum(u["in"] or 0 for u in uplinks)
        saude["uplink_out_octets"] = sum(u["out"] or 0 for u in uplinks)

    # PONs: le direto pelo indice calculado. GETNEXT nao serve aqui: a partir de
    # um indice inexistente o agente da AN5516 pula para a PROXIMA COLUNA
    # (ifType) em vez da proxima linha. Placa sem PON 1 nem 2 = slot vazio.
    pons_total = pons_up = 0
    for slot in range(1, 21):
        if all(_get(s, f"{_IF_DESCR}.{slot * _SLOT + pon * _PON}") is None for pon in (1, 2)):
            continue
        for pon in range(1, 17):
            idx = slot * _SLOT + pon * _PON
            nome = _get(s, f"{_IF_DESCR}.{idx}")
            if nome is None or not str(nome).upper().startswith("PON"):
                continue
            pons_total += 1
            pons_up += int(str(_get(s, f"{_IF_OPER}.{idx}")) == "1")
    saude["pons_total"] = pons_total
    saude["pons_up"] = pons_up
    return saude


def coletar_saude_olts(olts: List[Dict[str, Any]], community: str) -> Dict[str, Any]:
    """Uma rodada para as OLTs do cliente da sessao; guarda o resultado por OLT."""
    from app.services.db_store import get_json_state, set_json_state

    estado = dict(get_json_state(STATE_KEY, {}) or {})
    feitos = {}
    for olt in olts or []:
        if not olt.get("active", True) or not _e_fiberhome(olt):
            continue
        olt_id = str(olt.get("id"))
        try:
            _vnat.set_olt_reach_connector(olt.get("connector_id") or "")
            host = _vnat.reach_olt_ip(olt.get("host")) or olt.get("host")
            saude = coletar_saude_fiberhome(host, community)
            saude.update({"ok": True, "error": ""})
        except Exception as exc:
            logger.warning("Saude SNMP da OLT %s falhou: %s", olt.get("host"), exc)
            saude = {"ok": False, "error": str(exc)[:200]}
        agora = datetime.now(timezone.utc)
        saude["at"] = agora.isoformat()
        # bit/s entre esta leitura e a anterior. O sync com o Zabbix roda bem
        # mais vezes que esta coleta: mandar o contador cru e deixar o Zabbix
        # derivar dava 0 nos envios repetidos e um pico falso quando mudava.
        anterior = estado.get(olt_id) or {}
        try:
            dt = (agora - datetime.fromisoformat(anterior["at"])).total_seconds()
        except Exception:
            dt = 0
        for lado in ("in", "out"):
            atual, antes = saude.get(f"uplink_{lado}_octets"), anterior.get(f"uplink_{lado}_octets")
            if saude.get("ok") and anterior.get("ok") and dt > 0 and atual is not None and antes is not None and atual >= antes:
                saude[f"uplink_{lado}_bps"] = round((atual - antes) * 8 / dt)
        estado[olt_id] = saude
        feitos[olt_id] = {k: saude.get(k) for k in ("ok", "uptime_days", "uplinks_up", "pons_up", "error")}
    if feitos:
        set_json_state(STATE_KEY, estado)
    return {"ok": True, "olts": feitos}


def saude_das_olts() -> Dict[str, Any]:
    from app.services.db_store import get_json_state

    return dict(get_json_state(STATE_KEY, {}) or {})
