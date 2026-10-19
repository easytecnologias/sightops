#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Driver para gateways Ruijie Reyee (ex: EG105G-P-V2/V3, ReyeeOS).

Diferente do MikroTik (que roda um script local no proprio equipamento,
pensado pra CPEs atras de CGNAT sem IP publico), o Reyee normalmente tem
IP publico e nao expoe SSH/scripting pro usuario final -- entao aqui o
SightOps fala DIRETO com a API HTTP interna do proprio eWeb (a mesma que
a tela web usa), sem nada rodando dentro do equipamento. E o mesmo padrao
dos drivers de OLT (SightOps conecta quando precisa), so que por HTTP.

O login usa uma chave de firmware FIXA (nao muda por equipamento):
GibberishAES.dec('U2FsdGVkX19ecPYL/ZAlcSG29wb6ivqD9YjEM30k1h8=', 'eweb')
-> 'RjYkhwzx$2018!'. A senha do usuario e cifrada com essa chave em
AES-256-CBC, formato OpenSSL "Salted__" (KDF EVP_BytesToKey/MD5) --
o mesmo formato de `openssl enc -aes-256-cbc -a -salt -md md5`.

Validado em campo contra um EG105G-P-V2 real (ReyeeOS 2.340.0.1629):
login + listagem de ~180 dispositivos da LAN (MAC/IP/hostname/porta).
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from typing import Any, Dict, List

import requests  # type: ignore[import]
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

FIRMWARE_KEY = "RjYkhwzx$2018!"


class RuijieAuthError(Exception):
    """Login recusado pelo gateway (senha errada, ou bloqueio temporario)."""


def _evp_bytes_to_key(password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16) -> tuple[bytes, bytes]:
    """KDF EVP_BytesToKey/MD5 -- o mesmo do `openssl enc ... -md md5`."""
    derived = b""
    prev = b""
    while len(derived) < key_len + iv_len:
        prev = hashlib.md5(prev + password + salt).digest()
        derived += prev
    return derived[:key_len], derived[key_len:key_len + iv_len]


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len]) * pad_len


def encrypt_password(plaintext: str, passphrase: str = FIRMWARE_KEY) -> str:
    """Reproduz `openssl enc -aes-256-cbc -a -salt -md md5 -pass pass:<passphrase>`."""
    salt = os.urandom(8)
    key, iv = _evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    data = _pkcs7_pad(plaintext.encode("utf-8"))
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(data) + encryptor.finalize()
    return base64.b64encode(b"Salted__" + salt + ciphertext).decode("ascii")


class RuijieSession:
    """Sessao autenticada com o eWeb do gateway. Uma instancia = uma sessao."""

    def __init__(self, host: str, username: str, password: str, timeout: float = 15.0):
        self.host = host.strip()
        self.username = username.strip() or "admin"
        self.password = password
        self.timeout = timeout
        self.sid = ""
        self.sn = ""
        self._base = f"https://{self.host}"

    def login(self) -> None:
        body = {
            "method": "login",
            "params": {
                "password": encrypt_password(self.password),
                "username": self.username,
                "time": str(int(time.time())),
                "encry": True,
            },
        }
        resp = requests.post(f"{self._base}/cgi-bin/luci/api/auth", json=body, timeout=self.timeout, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0 or not isinstance(data.get("data"), dict):
            raise RuijieAuthError(f"login recusado pelo gateway: code={data.get('code')} {str(data.get('error') or data.get('msg') or '')[:200]}")
        self.sid = str(data["data"].get("sid") or "")
        self.sn = str(data["data"].get("sn") or "")
        if not self.sid or not self.sn:
            raise RuijieAuthError("login sem sid/sn na resposta do gateway")

    def call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.sid:
            self.login()
        resp = requests.post(
            f"{self._base}/cgi-bin/luci/api/cmd?auth={self.sid}",
            json={"method": method, "params": params},
            cookies={self.sn: self.sid},
            timeout=self.timeout,
            verify=False,
        )
        resp.raise_for_status()
        return resp.json()


def parse_user_list(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extrai a lista de dispositivos da resposta de `cmdArr(devSta.get/user_list)`."""
    rows: List[Dict[str, Any]] = []
    data = raw.get("data")
    if not isinstance(data, list):
        return rows
    for entry in data:
        if not isinstance(entry, dict):
            continue
        for item in entry.get("list") or []:
            if not isinstance(item, dict):
                continue
            rows.append({
                "mac": str(item.get("mac") or "").lower(),
                "ip": str(item.get("userIp") or ""),
                "hostname": str(item.get("hostName") or ""),
                "connect_type": str(item.get("connectType") or ""),
                "port": str(item.get("port") or ""),
                "ssid": str(item.get("ssid") or ""),
                "band": str(item.get("band") or ""),
                "vlan": str(item.get("access_vlan") or ""),
                "up_bytes": str(item.get("up") or item.get("flowUp") or ""),
                "down_bytes": str(item.get("down") or item.get("flowDown") or ""),
            })
    return rows


def _get(session: RuijieSession, method: str, module: str, data: Dict[str, Any] | None = None, no_parse: bool = False) -> Any:
    """Uma consulta de leitura (devSta.get / devConfig.get) e o `data` dela.

    Uma chamada por modulo de proposito: juntar varios num cmdArr so faz
    sentido se todos existirem -- um modulo que o firmware nao conhece
    devolve JSON quebrado e derruba a resposta inteira.
    """
    if method not in ("devSta.get", "devConfig.get"):
        raise ValueError(f"metodo de escrita nao permitido aqui: {method}")
    params: Dict[str, Any] = {"module": module, "noParse": no_parse, "async": None, "remoteIp": False}
    if data is not None:
        params["data"] = data
    raw = session.call("cmdArr", {"device": "pc", "params": [{"method": method, "params": params}]})
    if raw.get("code") != 0:
        # Nunca o `raw` inteiro: o erro vai para o cadastro, e uma resposta de
        # `network` com dados carregaria a senha PPPoE junto.
        raise RuntimeError(f"{module}: code={raw.get('code')} {str(raw.get('error') or '')[:200]}")
    itens = raw.get("data")
    return itens[0] if isinstance(itens, list) and itens else None


# Mensagens de alarme vem em chines no firmware (msgId nao e documentado).
# Traduz as conhecidas pelo texto; as outras passam como vieram.
_ALARMES_CONHECIDOS = (
    ("供电不足", "Alimentacao insuficiente (adaptador/PoE fora do padrao)"),
    ("IP冲突", "Conflito de IP na rede"),
    ("离线", "Equipamento offline"),
)


def _traduz_alarme(msg: str) -> str:
    for trecho, texto in _ALARMES_CONHECIDOS:
        if trecho in msg:
            return texto
    return msg


def _mac(value: Any) -> str:
    """'1082.3d47.4595' / '10-82-3D-...' / '10:82:3D:...' -> '10:82:3d:47:45:95'."""
    hexa = "".join(ch for ch in str(value or "").lower() if ch in "0123456789abcdef")
    if len(hexa) != 12:
        return str(value or "").lower()
    return ":".join(hexa[i:i + 2] for i in range(0, 12, 2))


def _lan_cidr(lan: Dict[str, Any]) -> str:
    import ipaddress

    try:
        return str(ipaddress.ip_network(f"{lan.get('ipaddr')}/{lan.get('netmask') or '255.255.255.0'}", strict=False))
    except ValueError:
        return ""


def parse_status(sysinfo: Any, arp: Any, user_list: Any, network: Any, remarks: Any,
                 ports: Any, flow: Any, neighbor: Any, alarms: Any, conflict: Any) -> Dict[str, Any]:
    """Junta as respostas cruas do eWeb no formato que o resto do SightOps le.

    `inventory` sai com as mesmas chaves do conector MikroTik (dhcp_rows,
    arp_rows, neighbor_rows, *_sample, lan_networks) -- e o que a ativacao
    de camera, a implantacao, a manutencao e o indice MAC->IP procuram.

    Do `network` so sai a parte de LAN: a WAN traz usuario e senha do PPPoE
    do provedor em texto puro e nada dela pode ser gravado.
    """
    sysinfo = sysinfo if isinstance(sysinfo, dict) else {}
    arp_list = (arp or {}).get("arpList") if isinstance(arp, dict) else []
    clientes = parse_user_list({"data": [user_list]}) if isinstance(user_list, dict) else []
    nomes = {}
    if isinstance(remarks, dict):
        nomes = {_mac(r.get("mac")): str(r.get("name") or "") for r in remarks.get("list") or [] if isinstance(r, dict)}

    lans = []
    wan_proto = ""
    if isinstance(network, dict):
        for lan in network.get("lan") or []:
            if not isinstance(lan, dict):
                continue
            cidr = _lan_cidr(lan)
            if cidr:
                lans.append({"cidr": cidr, "gateway": str(lan.get("ipaddr") or ""), "vlan": str(lan.get("vlanid") or ""),
                             "name": str(lan.get("desc") or "").strip(), "dhcp": str(lan.get("ignore") or "0") == "0"})
        wans = network.get("wan") or []
        if wans and isinstance(wans[0], dict):
            wan_proto = str(wans[0].get("proto") or "")

    dhcp_rows = [{"ip": c["ip"], "mac": c["mac"], "host": c["hostname"] or nomes.get(c["mac"], ""),
                  "status": "bound" if c["connect_type"] in ("wire", "wireless") else c["connect_type"],
                  "port": c["port"], "ssid": c["ssid"]}
                 for c in clientes if c["ip"] and c["mac"]]
    arp_rows = [{"ip": str(a.get("address") or ""), "mac": _mac(a.get("hardware")), "interface": str(a.get("intf") or "")}
                for a in arp_list or [] if isinstance(a, dict) and a.get("address")]
    # Modulo que nao respondeu fica None ("nao sei"), nunca lista vazia: sem
    # o `neighbor` todo AP pareceria fora do ar, sem `port_status` iria
    # "nenhuma porta com link", sem `alarm_mngt` iria "nenhum alarme".
    vizinhos = neighbor.get("neighbor") or [] if isinstance(neighbor, dict) else None
    todos_vizinhos = []
    for v in vizinhos or []:
        if not isinstance(v, dict):
            continue
        todos_vizinhos.append({"sn": str(v.get("devSN") or ""), "model": str(v.get("deviceType") or ""), "ip": str(v.get("ip") or ""),
                               "mac": _mac(v.get("devMac")), "role": str(v.get("role") or ""),
                               "product": str(v.get("product") or ""),
                               "firmware": str(v.get("software") or "").split(";")[0],
                               "name": nomes.get(_mac(v.get("devMac")), "")})
    neighbor_rows = [{"ip": a["ip"], "mac": a["mac"], "identity": a["name"] or a["sn"], "platform": a["model"]}
                     for a in todos_vizinhos]
    # So AP vira access_point; switch Reyee tambem aparece em `neighbor`.
    aps = None if vizinhos is None else [a for a in todos_vizinhos
                                         if a["role"].upper() == "AP" or a["product"].upper() == "EAP"]

    portas = None
    if isinstance(ports, dict):
        portas = [{"name": str(p.get("panel_name") or p.get("name") or ""), "up": str(p.get("status")) == "on",
                   "speed": str(p.get("speed") or ""), "duplex": str(p.get("duplex") or ""),
                   "poe": str(p.get("poe_direct") or "") == "out", "wan": str(p.get("name") or "") == "WAN"}
                  for p in ports.get("List") or [] if isinstance(p, dict)]

    wan_flow = {}
    if isinstance(flow, dict) and isinstance(flow.get("data"), dict):
        wan_flow = flow["data"].get("wan") or {}

    alarmes = None if not isinstance(alarms, dict) else []
    for grupo in alarms.get("list") or [] if isinstance(alarms, dict) else []:
        for d in (grupo or {}).get("detail") or []:
            if isinstance(d, dict):
                msg = str(d.get("msg") or "")
                alarmes.append({"sn": str(d.get("sn") or ""), "msg": _traduz_alarme(msg), "msg_original": msg,
                                "type": str(d.get("type") or ""), "time": d.get("time")})

    def _num(v: Any) -> int | None:
        try:
            return int(str(v))
        except (TypeError, ValueError):
            return None

    sys_mac = _mac(sysinfo.get("sys_mac"))
    return {
        "host": {
            "hostname": nomes.get(sys_mac, "") or str(sysinfo.get("serial_num") or ""),
            "os": "ReyeeOS",
            "model": str(sysinfo.get("model") or sysinfo.get("product_class") or ""),
            "serial": str(sysinfo.get("serial_num") or ""),
            "firmware": str(sysinfo.get("software_version") or "").split(";")[0],
            "mac": sys_mac,
            "wan_ip": str(sysinfo.get("wan_ip") or ""),
            "wan_proto": wan_proto,
            "lan_networks": [l["cidr"] for l in lans],
        },
        "inventory": {
            "dhcp_leases": len(dhcp_rows), "arp_entries": len(arp_rows), "neighbors": len(neighbor_rows),
            "dhcp_rows": dhcp_rows, "arp_rows": arp_rows, "neighbor_rows": neighbor_rows,
            "dhcp_sample": ";".join(f"{r['ip']}|{r['mac']}|{r['status']}" for r in dhcp_rows),
            "arp_sample": ";".join(f"{r['ip']}|{r['mac']}|{r['interface']}" for r in arp_rows),
            "neighbor_sample": ";".join(f"{r['ip']}|{r['mac']}|{r['identity']}" for r in neighbor_rows),
            "lan_networks": [l["cidr"] for l in lans],
            "ruijie_devices": clientes,
            "count": len(clientes),
        },
        "ruijie": {
            "lans": lans, "ports": portas, "aps": aps, "alarms": alarmes,
            "ip_conflict": bool(conflict.get("conflict_status")) if isinstance(conflict, dict) else None,
            "wan_up_bps": _num(wan_flow.get("up")), "wan_down_bps": _num(wan_flow.get("down")),
        },
    }


def collect_status(host: str, username: str, password: str, timeout: float = 15.0,
                   session: RuijieSession | None = None) -> Dict[str, Any]:
    """Estado completo do gateway numa sessao: sistema, ARP, clientes, LANs,
    portas, trafego da WAN, APs, alarmes. So leitura.

    `session` reaproveita um login anterior (a coleta roda a cada poucos
    minutos e o eWeb guarda as sessoes abertas); se ela expirou, loga de novo
    uma vez. Modulo opcional que falhar (firmware sem ele) fica vazio; so o
    `sysinfo` e obrigatorio -- sem ele nao da para dizer que o gateway respondeu.
    """
    if session is None or (session.host, session.username, session.password) != (host.strip(), username.strip() or "admin", password):
        session = RuijieSession(host, username, password, timeout=timeout)
    try:
        if not session.sid:
            session.login()
        sysinfo = _get(session, "devSta.get", "sysinfo", no_parse=True)
    except RuijieAuthError:
        raise
    except Exception:
        session.login()
        sysinfo = _get(session, "devSta.get", "sysinfo", no_parse=True)
    if not isinstance(sysinfo, dict) or not sysinfo.get("serial_num"):
        raise RuntimeError("gateway respondeu sem sysinfo")
    opcionais = {
        "arp": ("devSta.get", "arp", None, False),
        "user_list": ("devSta.get", "user_list", {"devType": "all", "dataType": "timely"}, True),
        "network": ("devConfig.get", "network", None, False),
        "remarks": ("devConfig.get", "devRemark", None, True),
        "ports": ("devSta.get", "port_status", None, False),
        "flow": ("devSta.get", "flow", {"func": "interface_info"}, True),
        "neighbor": ("devSta.get", "neighbor", None, True),
        "alarms": ("devSta.get", "alarm_mngt", None, True),
        "conflict": ("devSta.get", "conflict_status", None, True),
    }
    lidos: Dict[str, Any] = {}
    falhas: List[str] = []
    for nome, (method, module, data, no_parse) in opcionais.items():
        try:
            lidos[nome] = _get(session, method, module, data, no_parse)
        except Exception as exc:  # noqa: BLE001 -- modulo ausente nao derruba a coleta
            lidos[nome] = None
            falhas.append(f"{module}: {exc}")
    out = parse_status(sysinfo, **lidos)
    out["ok"] = True
    out["sn"] = session.sn
    out["module_errors"] = falhas
    out["session"] = session
    return out


def lan_inventory(host: str, username: str, password: str, timeout: float = 15.0) -> Dict[str, Any]:
    """Loga no gateway e devolve o inventario de dispositivos da LAN.

    Equivalente ao job `lan_inventory` do conector MikroTik, so que
    chamado direto pelo SightOps (sem agente rodando no equipamento).
    """
    session = RuijieSession(host, username, password, timeout=timeout)
    session.login()
    raw = session.call(
        "cmdArr",
        {
            "device": "pc",
            "params": [
                {
                    "method": "devSta.get",
                    "params": {
                        "module": "user_list",
                        "noParse": True,
                        "async": None,
                        "remoteIp": False,
                        "data": {"devType": "all", "dataType": "timely"},
                    },
                }
            ],
        },
    )
    devices = parse_user_list(raw)
    return {"ok": True, "sn": session.sn, "count": len(devices), "devices": devices}
