"""Gravador aberto > Rede: as quatro abas de LEITURA (nada aqui escreve).

- Caminho e banda: servidor -> conector -> IP virtual -> gravador, com o tempo
  de resposta medido na hora, e a rede/placa do gravador.
- Cameras na rede: por canal, IP, MAC e onde a camera esta ligada (ONU/PON ou
  porta de switch), cruzando com o inventario de cameras do cliente.
- Portas e acessos: Web (HTTP), RTSP, SDK (DVRIP), nuvem P2P, HTTPS, SNMP e UPnP.
- Alertas de rede: o estado dos alarmes vem do raio-x na tela; aqui vao as
  ultimas quedas do gravador e do conector vistas pelo monitoramento.

A edicao (IP, DNS, portas), o reiniciar e as correcoes de rede sao de outro
arquivo (gravador-rede-editar.js / recorder_rede.py), feitos em paralelo.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def _t(v: Any) -> str:
    return str(v or "").strip()


def _mac(v: Any) -> str:
    return re.sub(r"[^0-9a-f]", "", _t(v).lower())


def medir_resposta(g, vezes: int = 3) -> Dict[str, Any]:
    """Tempo de resposta do gravador pelo caminho real (conector + IP virtual)."""
    tempos: List[float] = []
    erro = ""
    for _ in range(vezes):
        t0 = time.monotonic()
        try:
            if g.marca == "hikvision":
                g._get("/ISAPI/System/time")
            else:
                g._get("/cgi-bin/global.cgi?action=getCurrentTime")
            tempos.append((time.monotonic() - t0) * 1000)
        except Exception as exc:   # um tempo ruim nao derruba a aba
            erro = _t(exc)
    if not tempos:
        return {"ok": False, "erro": erro or "o gravador nao respondeu"}
    return {"ok": True, "min_ms": round(min(tempos)), "media_ms": round(sum(tempos) / len(tempos)),
            "max_ms": round(max(tempos)), "amostras": len(tempos), "perdidas": vezes - len(tempos)}


def _pares_secao(pares: Dict[str, str], prefixo: str) -> Dict[str, str]:
    return {k[len(prefixo) + 1:]: v for k, v in pares.items() if k.startswith(prefixo + ".") or k.startswith(prefixo + "[")}


def portas_intelbras(g) -> Dict[str, Any]:
    """Portas e acessos lidos da configuracao (so getConfig e getInterfaces)."""
    pares: Dict[str, str] = {}
    falhas: List[str] = []
    for sec in ("Web", "RTSP", "DVRIP", "UPnP", "T2UServer", "Https", "SNMP", "Network"):
        try:
            pares.update(g.ler_config(sec))
        except Exception as exc:
            falhas.append(f"{sec}: {_t(exc)[:60]}")
    v = pares.get
    placa: Dict[str, Any] = {}
    try:
        txt = g._get("/cgi-bin/netApp.cgi?action=getInterfaces")
        campos = dict(l.split("=", 1) for l in txt.splitlines() if "=" in l)
        placa = {"nome": campos.get("netInterface[0].Name", ""),
                 "velocidade_mbps": int(campos.get("netInterface[0].Speed") or 0),
                 "conectada": campos.get("netInterface[0].ConnStatus", "") == "Connected"}
    except Exception:
        pass
    upnp_map = sum(1 for k, x in pares.items() if re.fullmatch(r"UPnP\.MapTable\[\d+\]\.Enable", k) and x == "true")
    return {
        "web": {"ligado": v("Web.Enable", "true") == "true", "porta": v("Web.Port", "")},
        "rtsp": {"ligado": v("RTSP.Enable", "true") == "true", "porta": v("RTSP.Port", "")},
        "sdk": {"porta": v("DVRIP.TCPPort", ""), "udp": v("DVRIP.UDPPort", "")},
        "https": {"ligado": v("Https.Enable") == "true", "porta": v("Https.Port", "") or v("DVRIP.SSLPort", "")},
        "snmp": {"ligado": v("SNMP.Enable") == "true"},
        "upnp": {"ligado": v("UPnP.Enable") == "true", "mapeamentos": upnp_map},
        "p2p": {"ligado": v("T2UServer[0].Enable") == "true", "servidor": v("T2UServer[0].Address", "")},
        "rede": {"dhcp": v("Network.eth0.DhcpEnable") == "true"},
        "placa": placa,
        "falhas": falhas,
    }


def onde_estao(canais: List[Dict[str, Any]], inventario_nvr: List[Dict[str, Any]], host: str) -> List[Dict[str, Any]]:
    """Por canal: IP, MAC (do inventario do gravador) e onde a camera esta
    ligada (inventario de cameras: OLT/PON/ONU ou switch/porta). Marca IP
    duplicado entre canais e camera cujo MAC aparece hoje com outro IP."""
    from app.services.inventory_json import load_inventory_json
    por_ip: Dict[str, Dict[str, Any]] = {}
    por_mac: Dict[str, Dict[str, Any]] = {}
    ips_do_mac: Dict[str, set] = {}
    for modo in ("olt", "switch", "basic"):
        try:
            linhas = load_inventory_json(mode=modo) or []
        except Exception:
            continue
        for c in linhas:
            if not isinstance(c, dict):
                continue
            ip = _t(c.get("ip") or c.get("camera_ip"))
            item = {**c, "_modo": modo}
            if ip:
                por_ip.setdefault(ip, item)
            if _mac(c.get("mac")):
                por_mac.setdefault(_mac(c.get("mac")), item)
                if ip:
                    ips_do_mac.setdefault(_mac(c.get("mac")), set()).add(ip)
    mac_canal: Dict[int, str] = {}
    for r in inventario_nvr:
        if _t(r.get("host")) == _t(host):
            try:
                mac_canal[int(r.get("channel") or 0)] = _t(r.get("camera_mac") or r.get("mac"))
            except (TypeError, ValueError):
                pass
    contagem: Dict[str, int] = {}
    for c in canais:
        if _t(c.get("ip")):
            contagem[_t(c.get("ip"))] = contagem.get(_t(c.get("ip")), 0) + 1
    saida = []
    for c in canais:
        ip = _t(c.get("ip"))
        if not ip:
            continue
        canal = int(c.get("canal") or 0)
        mac = mac_canal.get(canal, "")
        cam = por_ip.get(ip) or {}
        # MAC pelo inventario de cameras (o camera_mac das linhas do gravador
        # estava errado em 30 de 31 canais no gravador de teste). "Mudou de IP"
        # nao sai do inventario -- so a busca ao vivo do gravador (aba Canais).
        mac = _t(por_ip.get(ip, {}).get("mac")) or mac
        ip_novo = ""
        if cam.get("_modo") == "olt" or cam.get("onu_name"):
            onde = {"tipo": "onu", "texto": " · ".join(x for x in (_t(cam.get("olt_name")), f"PON {_t(cam.get('pon'))}" if _t(cam.get("pon")) else "", _t(cam.get("onu_name"))) if x)}
        elif _t(cam.get("switch_name")) or _t(cam.get("switch_port")) or _t(cam.get("port")):
            onde = {"tipo": "switch", "texto": " · ".join(x for x in (_t(cam.get("switch_name")), f"porta {_t(cam.get('switch_port') or cam.get('port'))}") if x)}
        else:
            onde = {"tipo": "", "texto": ""}
        saida.append({"canal": canal, "ip": ip, "mac": mac or _t(cam.get("mac")), "onde": onde,
                      "duplicado": contagem.get(ip, 0) > 1, "ip_novo": ip_novo})
    return saida


def quedas_recentes(host: str, conector: str, dias: int = 7, limite: int = 20) -> List[Dict[str, Any]]:
    """Ultimas quedas/voltas do gravador e do conector no monitoramento (cliente atual)."""
    from app.services import db_store
    tenant = db_store._current_tenant_slug()
    chaves = [f"nvr:{conector or 'local'}:{host}", f"dvr:{conector or 'local'}:{host}"]
    if conector:
        chaves.append(f"connector:{conector}")
    desde = (datetime.utcnow() - timedelta(days=max(1, min(int(dias), 30)))).isoformat(timespec="seconds")
    marcas = ",".join("?" for _ in chaves)
    with db_store._conn() as c:
        rows = c.execute(
            f"SELECT entity_key, entity_type, from_status, to_status, message, created_at FROM monitoring_events "
            f"WHERE tenant_slug=? AND entity_key IN ({marcas}) AND created_at >= ? ORDER BY created_at DESC LIMIT ?",
            (tenant, *chaves, desde, int(limite)),
        ).fetchall()
    return [{"quem": "conector" if _t(dict(r).get("entity_type")) == "connector" else "gravador",
             "de": _t(dict(r).get("from_status")), "para": _t(dict(r).get("to_status")),
             "mensagem": _t(dict(r).get("message")), "quando": _t(dict(r).get("created_at"))[:19]} for r in rows]
