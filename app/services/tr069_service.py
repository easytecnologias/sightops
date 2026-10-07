"""TR-069 das ONUs pelo GenieACS, separado por cliente.

Um GenieACS so atende todos os clientes. Ele nao sabe de tenant: quem decide de
quem e cada ONU e o SightOps, pelo SERIAL, cruzando com o inventario de OLT do
cliente da sessao. Serial e unico de fabrica; ONU que nao esta no inventario de
ninguem nao aparece para cliente nenhum.

Tres regras que nao podem se perder:

- **Senha por cliente.** Cada cliente tem usuario/senha de CWMP proprios
  (`tr069_config`, cifrada com a SIGHTOPS_SECRET_KEY). O `cwmp.auth` do GenieACS
  e gerado a partir de todos eles: sem isso ele aceita qualquer ONU.
- **Acao imediata pelo IP virtual.** O ConnectionRequestURL que a ONU informa e
  um IP da rede do cliente (ex.: 172.18.1.254), e essas faixas se repetem entre
  clientes. Quem chama a ONU e o SightOps, pelo vnat do conector dela -- nunca o
  GenieACS sozinho. IP fora das faixas do conector: nao chama, a tarefa espera o
  proximo contato (melhor atrasar do que bater na rede de outro cliente).
- **Dois padroes de parametro.** TR-098 (`InternetGatewayDevice.`) e TR-181
  (`Device.`); fabricante acrescenta `X_<OUI>_`. Tudo que a tela le passa por
  `resumo_do_dispositivo`, que entende os dois.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import string
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from requests.auth import HTTPDigestAuth

logger = logging.getLogger("cam-snapshot")

CONFIG_KEY = "tr069_config"
HISTORY_KEY = "tr069_history"
PLATFORM_KEY = "tr069_platform__tenant___plataforma"
HISTORY_MAX = 300
INFORM_PADRAO_S = 300


class Tr069Error(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# GenieACS (NBI)
# --------------------------------------------------------------------------- #

def _nbi_url() -> str:
    return os.getenv("SIGHTOPS_ACS_NBI_URL", "http://genieacs:7557").rstrip("/")


def _nbi(method: str, path: str, *, params: Optional[dict] = None, body: Any = None, timeout: float = 10.0) -> Any:
    url = f"{_nbi_url()}{path}"
    try:
        r = requests.request(method, url, params=params, json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise Tr069Error(f"servidor TR-069 fora do ar ({exc.__class__.__name__})") from exc
    if r.status_code >= 400:
        raise Tr069Error(f"servidor TR-069 recusou {method} {path}: HTTP {r.status_code} {r.text[:200]}")
    if not r.content:
        return None
    try:
        return r.json()
    except ValueError:
        return r.text


def _device_path(device_id: str) -> str:
    return "/devices/" + urllib.parse.quote(device_id, safe="")


# --------------------------------------------------------------------------- #
# Serial: o elo entre ONU do inventario e dispositivo do GenieACS
# --------------------------------------------------------------------------- #

def normalizar_serial(serial: Any) -> str:
    """HWTCDC390F9A, hwtc-dc390f9a e 48575443DC390F9A viram a mesma coisa.

    GPON tem serial de 4 letras de fabricante + 8 hex. Varios equipamentos
    informam no TR-069 a forma toda em hex (o fabricante em ASCII hex).
    """
    s = re.sub(r"[^0-9A-Za-z]", "", str(serial or "")).upper()
    if re.fullmatch(r"[0-9A-F]{16}", s):
        try:
            fabricante = bytes.fromhex(s[:8]).decode("ascii")
        except (ValueError, UnicodeDecodeError):
            return s
        if fabricante.isalpha():
            return fabricante.upper() + s[8:]
    return s


def _formas_do_serial(serial: str) -> List[str]:
    """Formas em que o mesmo serial pode estar gravado no GenieACS."""
    s = normalizar_serial(serial)
    formas = {s}
    if re.fullmatch(r"[A-Z]{4}[0-9A-F]{8}", s):
        formas.add(s[:4].encode("ascii").hex().upper() + s[4:])
    return sorted(formas)


def serial_do_inventario(serial: Any, onus: Dict[str, Any]) -> str:
    """Chave do inventario para o serial que a ONU informa ao TR-069.

    A 8820i guarda o serial SEM o prefixo do fabricante ("F1D35486"), mas a
    ONU se apresenta completa ("ITBSF1D35486"). Os 4 primeiros caracteres sao
    o fabricante; o resto e o que a OLT conhece.
    """
    d = normalizar_serial(serial)
    if d in onus:
        return d
    if re.fullmatch(r"[A-Z]{4}[0-9A-F]{8}", d) and d[4:] in onus:
        return d[4:]
    return d


def onus_do_cliente() -> Dict[str, Dict[str, Any]]:
    """serial normalizado -> linha de ONU do inventario do cliente da sessao."""
    from app.services.olt_service import list_macs

    por_serial: Dict[str, Dict[str, Any]] = {}
    for row in list_macs().get("rows", []) or []:
        s = normalizar_serial(row.get("onu_serial") or row.get("serial"))
        if len(s) >= 8 and s not in por_serial:
            por_serial[s] = row
    return por_serial


# --------------------------------------------------------------------------- #
# Leitura do modelo de dados (TR-098 e TR-181)
# --------------------------------------------------------------------------- #

def _no(doc: Dict[str, Any], caminho: str) -> Any:
    cur: Any = doc
    for parte in caminho.split("."):
        if not isinstance(cur, dict) or parte not in cur:
            return None
        cur = cur[parte]
    return cur


def _v(doc: Dict[str, Any], caminho: str) -> Any:
    no = _no(doc, caminho)
    return no.get("_value") if isinstance(no, dict) else None


def _instancias(doc: Dict[str, Any], caminho: str) -> List[Tuple[int, Dict[str, Any]]]:
    no = _no(doc, caminho)
    if not isinstance(no, dict):
        return []
    return sorted((int(k), v) for k, v in no.items() if k.isdigit() and isinstance(v, dict))


def _campo_x(no: Dict[str, Any], *sufixos: str) -> Any:
    """Parametro de fabricante (X_<OUI>_...) pelo sufixo, ex.: VlanMux8021p."""
    for chave, valor in (no or {}).items():
        if chave.startswith("X_") and isinstance(valor, dict) and any(chave.endswith("_" + s) for s in sufixos):
            return valor.get("_value")
    return None


def _vlan(v: Any) -> Optional[int]:
    """VLAN/prioridade: -1, 0 e vazio = nao usa."""
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    return str(v).strip().lower() in ("1", "true", "up", "enabled")


def _mbps(v: Any) -> Optional[int]:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def padrao(doc: Dict[str, Any]) -> str:
    return "tr098" if "InternetGatewayDevice" in doc else "tr181"


def resumo_do_dispositivo(doc: Dict[str, Any]) -> Dict[str, Any]:
    """O que a tela mostra de uma ONU, igual para TR-098 e TR-181."""
    tr = padrao(doc)
    r = "InternetGatewayDevice" if tr == "tr098" else "Device"
    dev = doc.get("_deviceId") or {}
    out: Dict[str, Any] = {
        "device_id": doc.get("_id"),
        "padrao": tr,
        "fabricante": dev.get("_Manufacturer") or _v(doc, f"{r}.DeviceInfo.Manufacturer"),
        "oui": dev.get("_OUI"),
        "modelo": dev.get("_ProductClass") or _v(doc, f"{r}.DeviceInfo.ModelName"),
        "serial_acs": dev.get("_SerialNumber"),
        "serial": normalizar_serial(dev.get("_SerialNumber")),
        "firmware": _v(doc, f"{r}.DeviceInfo.SoftwareVersion"),
        "hardware": _v(doc, f"{r}.DeviceInfo.HardwareVersion"),
        "uptime_s": _v(doc, f"{r}.DeviceInfo.UpTime"),
        "ultimo_contato": doc.get("_lastInform"),
        "ultimo_boot": doc.get("_lastBoot"),
        "registrado_em": doc.get("_registered"),
        "intervalo_s": _v(doc, f"{r}.ManagementServer.PeriodicInformInterval") or INFORM_PADRAO_S,
        "lan": [], "wan": [], "wifi": [], "hosts": [],
    }
    if tr == "tr098":
        for n, p in _instancias(doc, "InternetGatewayDevice.LANDevice.1.LANEthernetInterfaceConfig"):
            out["lan"].append({
                "porta": n, "habilitada": _bool(_v(p, "Enable")), "link": _bool(_v(p, "Status")),
                "status": _v(p, "Status"), "velocidade_mbps": _mbps(_v(p, "MaxBitRate")),
                "caminho": f"InternetGatewayDevice.LANDevice.1.LANEthernetInterfaceConfig.{n}",
            })
        for d, wd in _instancias(doc, "InternetGatewayDevice.WANDevice"):
            for c, wcd in _instancias(wd, "WANConnectionDevice"):
                for tipo in ("WANIPConnection", "WANPPPConnection"):
                    for i, w in _instancias(wcd, tipo):
                        out["wan"].append({
                            "nome": _v(w, "Name"), "tipo": "pppoe" if tipo == "WANPPPConnection" else "ip",
                            "modo": _v(w, "ConnectionType"), "habilitada": _bool(_v(w, "Enable")),
                            "status": _v(w, "ConnectionStatus"), "ip": _v(w, "ExternalIPAddress"),
                            "usuario": _v(w, "Username"), "uptime_s": _v(w, "Uptime"),
                            # VlanMux8021p e a PRIORIDADE 802.1p, nao a VLAN (na 140PoE
                            # as duas valem 7 na WAN de gerencia e enganam).
                            "vlan": _vlan(_campo_x(w, "VlanMuxID", "VLANID", "VlanID", "VLANIDMark")),
                            "prioridade": _vlan(_campo_x(w, "VlanMux8021p", "8021p", "Priority")),
                            "portas": _campo_x(w, "LanInterface", "PortBinding", "BindPort") or "",
                            "servico": _campo_x(w, "ServiceType", "ServiceList", "ConnectionService"),
                            "nat": _bool(_v(w, "NATEnabled")),
                            "caminho": f"InternetGatewayDevice.WANDevice.{d}.WANConnectionDevice.{c}.{tipo}.{i}",
                        })
        for n, w in _instancias(doc, "InternetGatewayDevice.LANDevice.1.WLANConfiguration"):
            out["wifi"].append({
                "indice": n, "habilitada": _bool(_v(w, "Enable")), "ssid": _v(w, "SSID"),
                "canal": _v(w, "Channel"), "clientes": _v(w, "TotalAssociations"), "padrao": _v(w, "Standard"),
                "caminho": f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{n}",
            })
        hosts = _instancias(doc, "InternetGatewayDevice.LANDevice.1.Hosts.Host")
    else:
        for n, p in _instancias(doc, "Device.Ethernet.Interface"):
            if _bool(_v(p, "Upstream")):
                continue
            out["lan"].append({
                "porta": n, "habilitada": _bool(_v(p, "Enable")), "link": _bool(_v(p, "Status")),
                "status": _v(p, "Status"), "velocidade_mbps": _mbps(_v(p, "CurrentBitRate") or _v(p, "MaxBitRate")),
                "caminho": f"Device.Ethernet.Interface.{n}",
            })
        for n, p in _instancias(doc, "Device.PPP.Interface"):
            out["wan"].append({
                "nome": _v(p, "Name") or _v(p, "Alias"), "tipo": "pppoe", "modo": "PPPoE",
                "habilitada": _bool(_v(p, "Enable")), "status": _v(p, "ConnectionStatus") or _v(p, "Status"),
                "ip": _v(p, "IPCP.LocalIPAddress"), "usuario": _v(p, "Username"), "uptime_s": None, "vlan": None,
                "caminho": f"Device.PPP.Interface.{n}",
            })
        for n, s in _instancias(doc, "Device.WiFi.SSID"):
            out["wifi"].append({
                "indice": n, "habilitada": _bool(_v(s, "Enable")), "ssid": _v(s, "SSID"),
                "canal": None, "clientes": _v(doc, f"Device.WiFi.AccessPoint.{n}.AssociatedDeviceNumberOfEntries"),
                "padrao": None, "caminho": f"Device.WiFi.SSID.{n}",
            })
        hosts = _instancias(doc, "Device.Hosts.Host")
    for _, h in hosts:
        out["hosts"].append({"nome": _v(h, "HostName"), "ip": _v(h, "IPAddress"),
                             "mac": _v(h, "MACAddress") or _v(h, "PhysAddress"), "ativo": _bool(_v(h, "Active"))})
    return out


def estado(resumo: Dict[str, Any], agora: Optional[float] = None) -> str:
    """'gerenciada' se fez contato dentro de 2 intervalos (+1 min de folga)."""
    try:
        visto = datetime.fromisoformat(str(resumo.get("ultimo_contato")).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return "aguardando"
    try:
        intervalo = int(resumo.get("intervalo_s") or INFORM_PADRAO_S)
    except (TypeError, ValueError):
        intervalo = INFORM_PADRAO_S
    agora = time.time() if agora is None else agora
    return "gerenciada" if agora - visto <= 2 * intervalo + 60 else "sem_contato"


# --------------------------------------------------------------------------- #
# Consultas do cliente
# --------------------------------------------------------------------------- #

_PROJECAO_LISTA = ",".join([
    "_id", "_deviceId", "_lastInform", "_lastBoot", "_registered",
    "InternetGatewayDevice.DeviceInfo", "InternetGatewayDevice.ManagementServer.PeriodicInformInterval",
    "InternetGatewayDevice.LANDevice.1.LANEthernetInterfaceConfig", "InternetGatewayDevice.WANDevice",
    "InternetGatewayDevice.LANDevice.1.WLANConfiguration",
    "Device.DeviceInfo", "Device.ManagementServer.PeriodicInformInterval", "Device.Ethernet.Interface",
    "Device.PPP.Interface", "Device.WiFi.SSID", "Device.WiFi.AccessPoint",
])


def _buscar_por_seriais(seriais: Iterable[str], projecao: str) -> List[Dict[str, Any]]:
    formas: List[str] = []
    curtos: List[str] = []
    for s in seriais:
        n = normalizar_serial(s)
        if re.fullmatch(r"[0-9A-F]{8}", n):
            curtos.append(n)  # serial sem fabricante (8820i): casa pelo final
        else:
            formas.extend(_formas_do_serial(n))
    queries = [{"_deviceId._SerialNumber": {"$in": formas[i:i + 200]}} for i in range(0, len(formas), 200)]
    queries += [{"_deviceId._SerialNumber": {"$regex": "^([A-Za-z]{4})?(" + "|".join(curtos[i:i + 150]) + ")$"}}
                for i in range(0, len(curtos), 150)]
    if not queries:
        return []
    out: List[Dict[str, Any]] = []
    vistos = set()
    for q in queries:
        query = json.dumps(q)
        params = {"query": query}
        if projecao:  # projection VAZIO trava o GenieACS 1.2 (15 s e lista vazia)
            params["projection"] = projecao
        for doc in _nbi("GET", "/devices/", params=params, timeout=20.0) or []:
            if doc.get("_id") not in vistos:
                vistos.add(doc.get("_id"))
                out.append(doc)
    return out


def _linha(resumo: Dict[str, Any], onu: Dict[str, Any]) -> Dict[str, Any]:
    wan = next((w for w in resumo["wan"] if w.get("habilitada")), resumo["wan"][0] if resumo["wan"] else {})
    return {
        **{k: resumo.get(k) for k in ("device_id", "serial", "fabricante", "modelo", "firmware", "padrao",
                                      "ultimo_contato", "ultimo_boot", "uptime_s")},
        "estado": estado(resumo),
        "olt": onu.get("olt_name"), "olt_ip": onu.get("olt_ip"),
        "pon": onu.get("pon_label") or onu.get("pon"), "onu_id": onu.get("onu_id"),
        "nome": onu.get("onu_name"), "site": onu.get("site"), "sinal_dbm": onu.get("rx_onu"),
        "status_onu": onu.get("oper_status"),
        "wan": {k: wan.get(k) for k in ("status", "ip", "vlan", "tipo")} if wan else None,
        "lan_com_link": sum(1 for p in resumo["lan"] if p.get("link")),
        "lan_total": len(resumo["lan"]),
        "wifi_clientes": sum(int(w.get("clientes") or 0) for w in resumo["wifi"]) if resumo["wifi"] else None,
        "tem_wifi": bool(resumo["wifi"]),
    }


def listar() -> Dict[str, Any]:
    """ONUs do cliente da sessao que conversam com o GenieACS + quantas nao."""
    onus = onus_do_cliente()
    linhas = []
    vistos = set()
    for doc in _buscar_por_seriais(onus.keys(), _PROJECAO_LISTA):
        resumo = resumo_do_dispositivo(doc)
        chave = serial_do_inventario(resumo["serial"], onus)
        onu = onus.get(chave)
        if not onu:  # nunca deveria: a busca ja foi pelos seriais do cliente
            continue
        vistos.add(chave)
        linhas.append(_linha(resumo, onu))
    contagem = {"gerenciada": 0, "sem_contato": 0, "aguardando": 0}
    for linha in linhas:
        contagem[linha["estado"]] = contagem.get(linha["estado"], 0) + 1
    pendentes = get_config_publica().get("aguardando") or {}
    if vistos & set(pendentes):
        _limpar_aguardando(vistos)  # fez o 1o contato: sai de "aguardando"
    aguardando = (set(pendentes) - vistos) & set(onus)
    contagem["aguardando"] += len(aguardando)
    for s in sorted(aguardando):
        onu = onus[s]
        linhas.append({"serial": s, "estado": "aguardando", "modelo": onu.get("onu_model"), "fabricante": "",
                       "olt": onu.get("olt_name"), "pon": onu.get("pon_label") or onu.get("pon"), "onu_id": onu.get("onu_id"),
                       "nome": onu.get("onu_name"), "sinal_dbm": onu.get("rx_onu"), "status_onu": onu.get("oper_status"),
                       "ativado_em": pendentes[s].get("em"), "metodo": pendentes[s].get("metodo"),
                       "wan": None, "lan_com_link": 0, "lan_total": 0, "tem_wifi": False})
    contagem["sem_tr069"] = len(set(onus) - vistos - aguardando)
    return {"ok": True, "onus": linhas, "contagem": contagem, "total_onus": len(onus)}


def _limpar_aguardando(vistos: set) -> None:
    from app.services.db_store import get_json_state, set_json_state

    cfg = dict(get_json_state(CONFIG_KEY, {}) or {})
    cfg["aguardando"] = {s: v for s, v in (cfg.get("aguardando") or {}).items() if s not in vistos}
    set_json_state(CONFIG_KEY, cfg)


def candidatas() -> Dict[str, Any]:
    """ONUs do inventario que ainda nao falam TR-069 (para o botao Ativar)."""
    onus = onus_do_cliente()
    com_tr069 = {serial_do_inventario(resumo_do_dispositivo(d)["serial"], onus)
                 for d in _buscar_por_seriais(onus.keys(), "_id,_deviceId")}
    linhas = [{"serial": s, "olt": r.get("olt_name"), "pon": r.get("pon_label") or r.get("pon"), "onu_id": r.get("onu_id"),
               "modelo": r.get("onu_model"), "nome": r.get("onu_name"), "status_onu": r.get("oper_status"),
               "sinal_dbm": r.get("rx_onu")}
              for s, r in onus.items() if s not in com_tr069]
    linhas.sort(key=lambda r: (str(r["status_onu"]).lower() != "active", str(r["olt"]), str(r["pon"]), int(r["onu_id"] or 0)))
    return {"ok": True, "onus": linhas}


def _documento_do_cliente(serial: str, projecao: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    onus = onus_do_cliente()
    s = serial_do_inventario(serial, onus)
    onu = onus.get(s)
    if not onu:
        # Mesmo erro para "nao existe" e "e de outro cliente": nao confirma serial alheio.
        raise Tr069Error("ONU nao encontrada neste cliente")
    docs = _buscar_por_seriais([s], projecao)
    if not docs:
        raise Tr069Error("esta ONU ainda nao fez contato com o servidor TR-069")
    return docs[0], onu


def detalhe(serial: str) -> Dict[str, Any]:
    doc, onu = _documento_do_cliente(serial)
    resumo = resumo_do_dispositivo(doc)
    from app.services import tr069_wan

    lista = tr069_wan.servicos(doc)
    return {"ok": True, **_linha(resumo, onu), "detalhe": resumo,
            "servicos": lista, "cenario": tr069_wan.cenario_atual(lista), "portas_lan": tr069_wan.portas_lan(doc),
            "historico": [h for h in historico() if h.get("serial") == resumo["serial"]][:30]}


# --------------------------------------------------------------------------- #
# Acoes
# --------------------------------------------------------------------------- #

def _tarefa(acao: str, resumo: Dict[str, Any], dados: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """(tarefa do GenieACS, descricao para o historico)."""
    if acao == "reiniciar":
        return {"name": "reboot"}, "Reiniciar ONU"
    if acao == "reset_fabrica":
        if normalizar_serial(dados.get("confirmar_serial")) != resumo["serial"]:
            raise Tr069Error("para o reset de fabrica, confirme digitando o serial da ONU")
        return {"name": "factoryReset"}, "Reset de fabrica"
    if acao == "ler":
        raiz = "InternetGatewayDevice" if resumo["padrao"] == "tr098" else "Device"
        return {"name": "refreshObject", "objectName": raiz}, "Ler dados da ONU"
    if acao == "porta_lan":
        porta = next((p for p in resumo["lan"] if p["porta"] == int(dados.get("porta") or 0)), None)
        if not porta:
            raise Tr069Error("porta LAN inexistente nesta ONU")
        ligar = bool(dados.get("habilitar"))
        return ({"name": "setParameterValues",
                 "parameterValues": [[porta["caminho"] + ".Enable", ligar, "xsd:boolean"]]},
                f"{'Ligar' if ligar else 'Desligar'} LAN {porta['porta']}")
    if acao == "wifi":
        rede = next((w for w in resumo["wifi"] if w["indice"] == int(dados.get("indice") or 0)), None)
        if not rede:
            raise Tr069Error("esta ONU nao tem essa rede Wi-Fi")
        valores = []
        ssid = str(dados.get("ssid") or "").strip()
        senha = str(dados.get("senha") or "")
        if ssid:
            if not 1 <= len(ssid) <= 32:
                raise Tr069Error("nome da rede Wi-Fi precisa ter de 1 a 32 caracteres")
            valores.append([rede["caminho"] + ".SSID", ssid, "xsd:string"])
        if senha:
            if not 8 <= len(senha) <= 63:
                raise Tr069Error("senha do Wi-Fi precisa ter de 8 a 63 caracteres")
            if resumo["padrao"] == "tr098":
                valores.append([rede["caminho"] + ".PreSharedKey.1.KeyPassphrase", senha, "xsd:string"])
            else:
                valores.append([f"Device.WiFi.AccessPoint.{rede['indice']}.Security.KeyPassphrase", senha, "xsd:string"])
        if not valores:
            raise Tr069Error("informe o nome da rede ou a senha")
        return {"name": "setParameterValues", "parameterValues": valores}, f"Alterar Wi-Fi {rede['indice']}"
    raise Tr069Error(f"acao desconhecida: {acao}")


def _url_de_chamada(doc: Dict[str, Any], connector_id: str) -> Optional[str]:
    """ConnectionRequestURL com o host trocado pelo IP virtual do conector.

    None = nao da para chamar com seguranca (sem URL, conector de outro cliente,
    ou IP fora das faixas mapeadas do conector).
    """
    from app.services import connector_routing_vnat as vnat

    raiz = "InternetGatewayDevice" if padrao(doc) == "tr098" else "Device"
    url = _v(doc, f"{raiz}.ManagementServer.ConnectionRequestURL")
    if not url:
        return None
    partes = urllib.parse.urlsplit(str(url))
    host = partes.hostname or ""
    if _em_rede_direta(host):
        # Rede de gerencia do proprio cliente, roteada direto (ex.: VLAN 7 da
        # Easy, 10.7.0.0/22, alcancada pelo CCR sem tunel). Declarada so pelo
        # dono da plataforma: o cliente nao aponta o servidor para rede alheia.
        return urllib.parse.urlunsplit((partes.scheme or "http", partes.netloc, partes.path or "/", partes.query, ""))
    virtual = vnat.virtual_ip_for(connector_id, host)
    if not virtual or virtual == vnat.IP_BLOQUEADO:
        return None
    if virtual == host and vnat.has_mapping(connector_id):
        return None  # fora das LANs do conector: poderia cair na rede de outro cliente
    netloc = virtual + (f":{partes.port}" if partes.port else "")
    return urllib.parse.urlunsplit((partes.scheme or "http", netloc, partes.path or "/", partes.query, ""))


_IP_GERENCIA_CACHE: Dict[str, Tuple[float, Dict[str, str]]] = {}


def onus_por_ip_de_gerencia() -> Dict[str, str]:
    """IP de gerencia (o do ConnectionRequestURL) -> conector, so das ONUs do
    cliente da sessao. Usado pelo acesso web do SightOps (botao "Abrir web").
    Cache de 60 s por cliente: o proxy chama isto a cada requisicao da pagina."""
    from app.core.tenant_context import get_current_tenant_slug

    chave = get_current_tenant_slug()
    agora = time.time()
    em_cache = _IP_GERENCIA_CACHE.get(chave)
    if em_cache and agora - em_cache[0] < 60:
        return em_cache[1]
    onus = onus_do_cliente()
    out: Dict[str, str] = {}
    projecao = "_id,_deviceId,InternetGatewayDevice.ManagementServer.ConnectionRequestURL,Device.ManagementServer.ConnectionRequestURL"
    for doc in _buscar_por_seriais(onus.keys(), projecao):
        raiz = "InternetGatewayDevice" if padrao(doc) == "tr098" else "Device"
        host = urllib.parse.urlsplit(str(_v(doc, f"{raiz}.ManagementServer.ConnectionRequestURL") or "")).hostname
        onu = onus.get(serial_do_inventario((doc.get("_deviceId") or {}).get("_SerialNumber"), onus)) or {}
        if host:
            out[host] = str(onu.get("connector_id") or onu.get("remote_connector_id") or "")
    _IP_GERENCIA_CACHE[chave] = (agora, out)
    return out


def redes_diretas() -> List[str]:
    from app.services.db_store import get_json_state

    return list((get_json_state(CONFIG_KEY, {}) or {}).get("redes_diretas") or [])


def _em_rede_direta(host: str) -> bool:
    import ipaddress

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    for rede in redes_diretas():
        try:
            if ip in ipaddress.ip_network(rede, strict=False):
                return True
        except ValueError:
            continue
    return False


def salvar_redes_diretas(redes: List[str]) -> List[str]:
    """So o dono da plataforma chama (conferido na rota)."""
    import ipaddress

    from app.services.db_store import set_json_state

    limpas = []
    for r in redes or []:
        try:
            n = ipaddress.ip_network(str(r).strip(), strict=False)
        except ValueError as exc:
            raise Tr069Error(f"rede invalida: {r}") from exc
        if n.version != 4 or not n.is_private or not 16 <= n.prefixlen <= 30:
            raise Tr069Error(f"{r}: use uma rede privada IPv4 entre /16 e /30")
        limpas.append(str(n))
    cfg = garantir_credencial()
    cfg["redes_diretas"] = sorted(set(limpas))
    set_json_state(CONFIG_KEY, cfg)
    return cfg["redes_diretas"]


def _chamar_onu(doc: Dict[str, Any], connector_id: str) -> Tuple[bool, str]:
    url = _url_de_chamada(doc, connector_id)
    if not url:
        return False, "sem caminho seguro ate a ONU; vai no proximo contato"
    raiz = "InternetGatewayDevice" if padrao(doc) == "tr098" else "Device"
    usuario = _v(doc, f"{raiz}.ManagementServer.ConnectionRequestUsername") or ""
    senha = _v(doc, f"{raiz}.ManagementServer.ConnectionRequestPassword") or ""
    try:
        r = requests.get(url, auth=HTTPDigestAuth(str(usuario), str(senha)), timeout=6)
    except requests.RequestException as exc:
        return False, f"a ONU nao atendeu ({exc.__class__.__name__}); vai no proximo contato"
    if r.status_code in (200, 204):
        return True, "chamada atendida"
    return False, f"a ONU recusou a chamada (HTTP {r.status_code}); vai no proximo contato"


def _esperar_tarefa(task_id: str, device_id: str, limite_s: float = 25.0) -> str:
    """'aplicada', 'falhou: ...' ou 'na_fila'."""
    fim = time.time() + limite_s
    while time.time() < fim:
        # Tarefa recusada pela ONU CONTINUA na fila (e o GenieACS tenta de novo a
        # cada contato): olhar a falha a cada volta e tirar a tarefa da fila.
        falhas = _nbi("GET", "/faults/", params={"query": json.dumps({"device": device_id})}) or []
        falha = next((f for f in falhas if str(f.get("_id", "")).endswith(":task_" + task_id)), None)
        if falha:
            for caminho in ("/tasks/" + task_id, "/faults/" + urllib.parse.quote(str(falha["_id"]), safe="")):
                try:
                    _nbi("DELETE", caminho)
                except Tr069Error:
                    pass
            detalhe = falha.get("detail") or {}
            nomes = [x.get("parameterName", "").rsplit(".", 1)[-1] for x in detalhe.get("setParameterValuesFault") or []]
            return "falhou: " + str(detalhe.get("faultString") or falha.get("code") or "erro na ONU") + (
                f" ({', '.join(nomes)})" if nomes else "")
        pendentes = _nbi("GET", "/tasks/", params={"query": json.dumps({"_id": task_id}), "projection": "_id"}) or []
        if not pendentes:
            return "aplicada"
        time.sleep(1.5)
    return "na_fila"


def _tarefa_e_espera(doc: Dict[str, Any], connector_id: str, tarefa: Dict[str, Any], limite_s: float = 25.0) -> Tuple[str, str]:
    criada = _nbi("POST", _device_path(doc["_id"]) + "/tasks", body=tarefa) or {}
    chamou, motivo = _chamar_onu(doc, connector_id)
    if not chamou:
        return "na_fila", motivo
    return _esperar_tarefa(str(criada.get("_id") or ""), doc["_id"], limite_s=limite_s), ""


def _religar_porta(doc, resumo, onu, dados) -> Tuple[str, str, str, Dict[str, Any]]:
    """PoE da 140PoE nao tem parametro proprio: desligar a porta corta a energia.
    Desliga, espera 5 s e liga de novo -- o mesmo que funcionou a mao na SIERRA."""
    porta = next((p for p in resumo["lan"] if p["porta"] == int(dados.get("porta") or 0)), None)
    if not porta:
        raise Tr069Error("escolha a porta LAN para religar")
    conector = str(onu.get("connector_id") or onu.get("remote_connector_id") or "")
    caminho = porta["caminho"] + ".Enable"
    desc = f"Religar PoE da LAN {porta['porta']}"
    res, motivo = _tarefa_e_espera(doc, conector, {"name": "setParameterValues", "parameterValues": [[caminho, False, "xsd:boolean"]]})
    if res != "aplicada":
        return desc, res, motivo, {}
    time.sleep(5)
    res, motivo = _tarefa_e_espera(doc, conector, {"name": "setParameterValues", "parameterValues": [[caminho, True, "xsd:boolean"]]})
    if res != "aplicada":
        # ficou DESLIGADA: diz isso claramente, a camera esta sem energia
        return desc, "falhou: a porta desligou mas nao religou", motivo or "religue a porta pela tela", {}
    return desc, res, "", {}


def _ping(doc, resumo, onu, dados) -> Tuple[str, str, str, Dict[str, Any]]:
    host = str(dados.get("host") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9.\-]{1,253}", host):
        raise Tr069Error("informe o IP ou nome para pingar")
    if resumo["padrao"] != "tr098":
        raise Tr069Error("ping pela ONU ainda nao mapeado para este modelo")
    base = "InternetGatewayDevice.IPPingDiagnostics"
    conector = str(onu.get("connector_id") or onu.get("remote_connector_id") or "")
    desc = f"Ping pela ONU para {host}"
    res, motivo = _tarefa_e_espera(doc, conector, {"name": "setParameterValues", "parameterValues": [
        [f"{base}.Host", host, "xsd:string"], [f"{base}.NumberOfRepetitions", 4, "xsd:unsignedInt"],
        [f"{base}.Timeout", 1000, "xsd:unsignedInt"], [f"{base}.DiagnosticsState", "Requested", "xsd:string"]]})
    if res != "aplicada":
        return desc, res, motivo, {}
    resultado: Dict[str, Any] = {}
    for _ in range(4):  # 4 pings de ate 1 s; a ONU avisa quando termina
        time.sleep(4)
        res, motivo = _tarefa_e_espera(doc, conector, {"name": "refreshObject", "objectName": base})
        if res != "aplicada":
            return desc, res, motivo, {}
        novo, _ = _documento_do_cliente(resumo["serial"], projecao=base)
        estado_diag = _v(novo, f"{base}.DiagnosticsState")
        if estado_diag and estado_diag != "Requested":
            resultado = {"estado": estado_diag, "ok": _v(novo, f"{base}.SuccessCount"), "falhas": _v(novo, f"{base}.FailureCount"),
                         "media_ms": _v(novo, f"{base}.AverageResponseTime"), "max_ms": _v(novo, f"{base}.MaximumResponseTime")}
            break
    if not resultado:
        return desc, "falhou: a ONU nao terminou o ping", "", {}
    detalhe = f"{resultado['ok']} de 4 responderam, media {resultado['media_ms']} ms"
    return desc, "aplicada", detalhe, {"ping": resultado}


def executar(serial: str, acao: str, dados: Optional[Dict[str, Any]], autor: str) -> Dict[str, Any]:
    dados = dados or {}
    doc, onu = _documento_do_cliente(serial)
    if acao in ("religar_porta", "ping"):
        resumo = resumo_do_dispositivo(doc)
        desc, resultado, detalhe, extra = (_religar_porta if acao == "religar_porta" else _ping)(doc, resumo, onu, dados)
        registro = {"em": datetime.now(timezone.utc).isoformat(), "serial": resumo["serial"], "acao": acao,
                    "descricao": desc, "autor": autor, "resultado": resultado, "detalhe": detalhe}
        _registrar(registro)
        return {"ok": not resultado.startswith("falhou"), **registro, **extra}
    resumo = resumo_do_dispositivo(doc)
    tarefa, descricao = _tarefa(acao, resumo, dados)
    # Sem ?connection_request: o GenieACS chamaria o IP da rede do cliente pela
    # tabela de rotas principal. Quem chama e o SightOps, pelo conector.
    criada = _nbi("POST", _device_path(resumo["device_id"]) + "/tasks", body=tarefa) or {}
    task_id = str(criada.get("_id") or "")
    chamou, motivo = _chamar_onu(doc, str(onu.get("connector_id") or onu.get("remote_connector_id") or ""))
    resultado = _esperar_tarefa(task_id, resumo["device_id"]) if (chamou and task_id) else "na_fila"
    registro = {
        "em": datetime.now(timezone.utc).isoformat(), "serial": resumo["serial"], "acao": acao,
        "descricao": descricao, "autor": autor, "resultado": resultado,
        "detalhe": "" if resultado == "aplicada" else motivo if not chamou else "",
    }
    _registrar(registro)
    return {"ok": not resultado.startswith("falhou"), **registro}


def historico() -> List[Dict[str, Any]]:
    from app.services.db_store import get_json_state

    return list(get_json_state(HISTORY_KEY, []) or [])


def _registrar(registro: Dict[str, Any]) -> None:
    from app.services.db_store import set_json_state

    set_json_state(HISTORY_KEY, ([registro] + historico())[:HISTORY_MAX])


# --------------------------------------------------------------------------- #
# Credenciais por cliente e cwmp.auth
# --------------------------------------------------------------------------- #

def _senha_nova() -> str:
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(24))


def _usuario_do_cliente(slug: str) -> str:
    return re.sub(r"[^a-z0-9]", "", slug.lower())[:24] or "cliente"


def garantir_credencial() -> Dict[str, Any]:
    """Cria (uma vez) o usuario/senha de CWMP do cliente da sessao."""
    from app.core.crypto import encrypt
    from app.core.tenant_context import get_current_tenant_slug
    from app.services.db_store import get_json_state, set_json_state

    cfg = dict(get_json_state(CONFIG_KEY, {}) or {})
    if not cfg.get("password_enc"):
        cfg.update({"username": _usuario_do_cliente(get_current_tenant_slug()),
                    "password_enc": encrypt(_senha_nova()),
                    "criada_em": datetime.now(timezone.utc).isoformat()})
        cfg.setdefault("auto_ativar", True)
        cfg.setdefault("intervalo_s", INFORM_PADRAO_S)
        set_json_state(CONFIG_KEY, cfg)
    return cfg


def credencial() -> Tuple[str, str]:
    """(usuario, senha em claro) -- so para o driver da OLT, nunca para a tela."""
    from app.core.crypto import decrypt

    cfg = garantir_credencial()
    return cfg["username"], decrypt(cfg["password_enc"])


def trocar_senha() -> Dict[str, Any]:
    from app.core.crypto import encrypt
    from app.services.db_store import set_json_state

    cfg = garantir_credencial()
    cfg["password_enc"] = encrypt(_senha_nova())
    cfg["trocada_em"] = datetime.now(timezone.utc).isoformat()
    set_json_state(CONFIG_KEY, cfg)
    return get_config_publica()


def get_config_publica() -> Dict[str, Any]:
    from app.services.db_store import get_json_state

    cfg = dict(get_json_state(CONFIG_KEY, {}) or {})
    return {
        "username": cfg.get("username") or "",
        "tem_senha": bool(cfg.get("password_enc")),
        "auto_ativar": bool(cfg.get("auto_ativar", True)),
        "intervalo_s": int(cfg.get("intervalo_s") or INFORM_PADRAO_S),
        "criada_em": cfg.get("criada_em"), "trocada_em": cfg.get("trocada_em"),
        "aguardando": cfg.get("aguardando") or {},
        "redes_diretas": cfg.get("redes_diretas") or [],
        "vlan_gerencia": cfg.get("vlan_gerencia"),
    }


def salvar_preferencias(dados: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.db_store import set_json_state

    cfg = garantir_credencial()
    if "auto_ativar" in dados:
        cfg["auto_ativar"] = bool(dados["auto_ativar"])
    if "vlan_gerencia" in dados:
        v = dados["vlan_gerencia"]
        if v in (None, "", 0, "0"):
            cfg.pop("vlan_gerencia", None)
        else:
            v = int(v)
            if not 2 <= v <= 4094:
                raise Tr069Error("VLAN de gerencia vai de 2 a 4094")
            cfg["vlan_gerencia"] = v
    if "intervalo_s" in dados:
        intervalo = int(dados["intervalo_s"])
        if intervalo not in (300, 900, 3600):
            raise Tr069Error("intervalo de contato aceito: 5, 15 ou 60 minutos")
        cfg["intervalo_s"] = intervalo
    set_json_state(CONFIG_KEY, cfg)
    return get_config_publica()


def expressao_cwmp_auth(credenciais: Iterable[Tuple[str, str]], aceitar_legada: bool) -> str:
    """Expressao do `cwmp.auth`: aceita a ONU que mandar a senha de algum cliente.

    A legada (acs/acs) existe so enquanto as ONUs ativadas antes da senha por
    cliente nao forem reenviadas; depois `aceitar_legada` vai para False.
    """
    partes = []
    for usuario, senha in credenciais:
        if not re.fullmatch(r"[A-Za-z0-9]+", usuario or "") or not re.fullmatch(r"[A-Za-z0-9]+", senha or ""):
            raise Tr069Error(f"credencial invalida para o cwmp.auth: {usuario!r}")
        partes.append(f'AUTH("{usuario}", "{senha}")')
    if aceitar_legada:
        partes.append('AUTH("acs", "acs")')
    return " OR ".join(partes) if partes else "false"


def sincronizar_cwmp_auth(aplicar: bool = False) -> Dict[str, Any]:
    """Gera o cwmp.auth com a senha de todos os clientes; grava se `aplicar`."""
    from app.core.crypto import decrypt
    from app.services.auth_store import existing_tenant_slugs
    from app.services.db_store import get_json_state

    creds = []
    for slug in sorted(existing_tenant_slugs()):
        cfg = get_json_state(f"{CONFIG_KEY}__tenant__{slug}", {}) or {}
        if cfg.get("password_enc"):
            creds.append((str(cfg["username"]), decrypt(str(cfg["password_enc"]))))
    plataforma = get_json_state(PLATFORM_KEY, {}) or {}
    legada = bool(plataforma.get("aceitar_legada", True))
    expr = expressao_cwmp_auth(creds, legada)
    if aplicar:
        _gravar_config("cwmp.auth", expr)
    return {"ok": True, "clientes": len(creds), "aceita_legada": legada, "aplicado": aplicar}


def _gravar_config(nome: str, valor: str) -> None:
    """Grava uma chave de configuracao do GenieACS e confere lendo de volta.

    A NBI (7557) so LE configuracao; gravar e pela API da tela (3000), com o
    login do SightOps no GenieACS (SIGHTOPS_ACS_UI_USER/PASSWORD no .env.v3).
    """
    ui = os.getenv("SIGHTOPS_ACS_UI_URL", "http://genieacs:3000").rstrip("/")
    usuario, senha = os.getenv("SIGHTOPS_ACS_UI_USER", ""), os.getenv("SIGHTOPS_ACS_UI_PASSWORD", "")
    if not usuario or not senha:
        raise Tr069Error("login do SightOps no GenieACS nao configurado (SIGHTOPS_ACS_UI_USER/PASSWORD)")
    s = requests.Session()
    try:
        r = s.post(f"{ui}/login", json={"username": usuario, "password": senha}, timeout=8)
        if r.status_code != 200:
            raise Tr069Error(f"GenieACS recusou o login do SightOps (HTTP {r.status_code})")
        r = s.put(f"{ui}/api/config/{urllib.parse.quote(nome, safe='')}", json={"value": valor}, timeout=8)
        if r.status_code >= 400:
            raise Tr069Error(f"GenieACS recusou gravar {nome} (HTTP {r.status_code} {r.text[:120]})")
    except requests.RequestException as exc:
        raise Tr069Error(f"tela do GenieACS fora do ar ({exc.__class__.__name__})") from exc
    lido = next((c.get("value") for c in (_nbi("GET", "/config/") or []) if c.get("_id") == nome), None)
    if lido != valor:
        raise Tr069Error(f"{nome} nao ficou gravado no GenieACS (lido de volta: {str(lido)[:60]!r})")


def saude() -> Dict[str, Any]:
    try:
        _nbi("GET", "/devices/", params={"query": "{}", "projection": "_id", "limit": "1"}, timeout=4)
        return {"ok": True}
    except Tr069Error as exc:
        return {"ok": False, "error": str(exc)}
