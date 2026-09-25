"""NetSDK da Intelbras/Dahua (libdhnetsdk.so) pelo ctypes.

Existe por um motivo unico: **ativar camera de fabrica**. Camera nova nao tem
senha, entao nenhuma chamada HTTP/CGI do resto do projeto fala com ela -- tudo
responde 401. A propria Intelbras confirma que a API HTTP nao inicializa
dispositivo; quem faz isso e o NetSDK, o mesmo motor do IP Utility.

Duas funcoes so:

- `search_devices(ips)`  -> `CLIENT_SearchDevicesByIPs`, unicast por lista de IPs
  (nao e broadcast, entao **atravessa o tunel do conector**), devolve modelo,
  MAC, firmware e o estado de inicializacao de cada uma.
- `init_device(...)`     -> `CLIENT_InitDevAccountByIP`, cria a conta admin.
  A variante sem `ByIP` existe mas usa broadcast e NAO serve remoto.

**Tudo aqui fala com IP VIRTUAL (vnat)**, igual ao resto do app: o container
roda em bridge e nao enxerga as interfaces `wgc<N>` do host. Provado em
2026-09-25 no conector CANAPI -- o SDK rodou dentro do `sightops-v3-api` e
enxergou as cameras pelo IP virtual sem nenhum agente no host.

A lib nao vem no repo (50MB+). O Dockerfile copia de `deploy/netsdk/` para
`NETSDK_LIB_DIR`; sem ela o modulo carrega normalmente e `available()` devolve
False -- a tela avisa em vez de quebrar.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import (
    CFUNCTYPE, POINTER, Structure, c_bool, c_char, c_char_p, c_int, c_ubyte,
    c_uint, c_ushort, c_void_p,
)
from typing import Any, Dict, List, Optional

LIB_DIR = os.getenv("NETSDK_LIB_DIR", "/opt/netsdk/lib")
LIB_NAME = "libdhnetsdk.so"

# Limite do proprio SDK (DH_MAX_SAERCH_IP_NUM no dhnetsdk.h).
MAX_SEARCH_IPS = 256

# byInitStatus & 0x03 -- ver dhnetsdk.h, DEVICE_NET_INFO_EX.
INIT_LEGACY = 0      # aparelho antigo: nao suporta inicializacao
INIT_PENDING = 1     # de fabrica, SEM senha -- e o que a tela quer achar
INIT_DONE = 2        # ja inicializada

# byPwdResetWay -- qual dado de recuperacao o device exige no init.
RESET_PHONE = 0b01
RESET_EMAIL = 0b10


class DEVICE_NET_INFO_EX(Structure):
    """Espelho de dhnetsdk.h. A ordem e o tamanho dos campos importam byte a
    byte -- qualquer campo fora de lugar embaralha todo o resto da struct."""

    _fields_ = [
        ("iIPVersion", c_int),
        ("szIP", c_char * 64),
        ("nPort", c_int),
        ("szSubmask", c_char * 64),
        ("szGateway", c_char * 64),
        ("szMac", c_char * 40),
        ("szDeviceType", c_char * 32),
        ("byManuFactory", c_ubyte),
        ("byDefinition", c_ubyte),
        ("bDhcpEn", c_bool),
        ("byReserved1", c_ubyte),
        ("verifyData", c_char * 88),
        ("szSerialNo", c_char * 48),
        ("szDevSoftVersion", c_char * 128),
        ("szDetailType", c_char * 32),
        ("szVendor", c_char * 128),
        ("szDevName", c_char * 64),
        ("szUserName", c_char * 16),
        ("szPassWord", c_char * 16),
        ("nHttpPort", c_ushort),
        ("wVideoInputCh", c_ushort),
        ("wRemoteVideoInputCh", c_ushort),
        ("wVideoOutputCh", c_ushort),
        ("wAlarmInputCh", c_ushort),
        ("wAlarmOutputCh", c_ushort),
        ("bNewWordLen", c_int),
        ("szNewPassWord", c_char * 64),
        ("byInitStatus", c_ubyte),
        ("byPwdResetWay", c_ubyte),
        ("bySpecialAbility", c_ubyte),
        ("szNewDetailType", c_char * 64),
        ("bNewUserName", c_int),
        ("szNewUserName", c_char * 64),
        ("cReserved", c_char * 41),
    ]


class DEVICE_IP_SEARCH_INFO(Structure):
    _fields_ = [
        ("dwSize", c_uint),
        ("nIpNum", c_int),
        ("szIP", (c_char * 64) * MAX_SEARCH_IPS),
    ]


class NET_IN_INIT_DEVICE_ACCOUNT(Structure):
    _fields_ = [
        ("dwSize", c_uint),
        ("szMac", c_char * 40),
        ("szUserName", c_char * 128),
        ("szPwd", c_char * 128),
        ("szCellPhone", c_char * 32),
        ("szMail", c_char * 64),
        ("byInitStatus", c_ubyte),
        ("byPwdResetWay", c_ubyte),
        ("byReserved", c_ubyte * 2),
    ]


class NET_OUT_INIT_DEVICE_ACCOUNT(Structure):
    _fields_ = [("dwSize", c_uint)]


_SEARCH_CB = CFUNCTYPE(None, POINTER(DEVICE_NET_INFO_EX), c_void_p)

# O SDK e um singleton com estado global (CLIENT_Init/CLIENT_Cleanup contam
# referencia no processo inteiro). Uma instancia so, sob lock: duas buscas em
# paralelo embaralham o callback.
_lock = threading.Lock()
_sdk: Optional[ctypes.CDLL] = None
_load_error = ""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decode(raw: bytes) -> str:
    return (raw or b"").decode("utf-8", errors="replace").strip()


def _load() -> Optional[ctypes.CDLL]:
    """Carrega a lib uma vez. Sem ela o resto do app segue funcionando."""
    global _sdk, _load_error
    if _sdk is not None or _load_error:
        return _sdk
    path = os.path.join(LIB_DIR, LIB_NAME)
    try:
        # As libs irmas (libavnetsdk, libInfra...) sao resolvidas por RPATH/
        # LD_LIBRARY_PATH; carregar com RTLD_GLOBAL evita simbolo faltando.
        lib = ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
        lib.CLIENT_Init.restype = c_bool
        lib.CLIENT_SearchDevicesByIPs.restype = c_bool
        lib.CLIENT_InitDevAccountByIP.restype = c_bool
        lib.CLIENT_GetLastError.restype = c_uint
        if not lib.CLIENT_Init(None, 0):
            _load_error = "CLIENT_Init falhou"
            return None
        _sdk = lib
    except OSError as exc:
        _load_error = f"{type(exc).__name__}: {exc}"
        return None
    return _sdk


def available() -> Dict[str, Any]:
    """Estado da lib, pra tela poder explicar o motivo em vez de so falhar."""
    with _lock:
        lib = _load()
    return {
        "ok": bool(lib),
        "lib_dir": LIB_DIR,
        "error": _load_error or "",
    }


def _last_error(lib: ctypes.CDLL) -> str:
    try:
        return f"0x{lib.CLIENT_GetLastError():x}"
    except Exception:
        return ""


def search_devices(ips: List[str], wait_ms: int = 6000) -> Dict[str, Any]:
    """Sonda esses IPs (unicast) e devolve o que respondeu.

    O SDK chama o callback mais de uma vez pro mesmo aparelho (uma por rota/
    protocolo que enxerga), entao a deduplicacao por MAC nao e opcional.
    """
    alvos = [_text(ip) for ip in ips if _text(ip)][:MAX_SEARCH_IPS]
    if not alvos:
        return {"ok": True, "devices": [], "scanned": 0}

    with _lock:
        lib = _load()
        if not lib:
            return {"ok": False, "error": _load_error, "devices": [], "scanned": 0}

        achados: Dict[str, Dict[str, Any]] = {}

        def on_found(ptr, _user):  # roda em thread do SDK
            try:
                d = ptr.contents
                mac = _decode(d.szMac).lower()
                if not mac or mac in achados:
                    return
                init = d.byInitStatus & 0x03
                achados[mac] = {
                    "ip": _decode(d.szIP),
                    "mac": mac,
                    "model": _decode(d.szDetailType) or _decode(d.szDeviceType),
                    "serial": _decode(d.szSerialNo),
                    "firmware": _decode(d.szDevSoftVersion),
                    "device_name": _decode(d.szDevName),
                    "http_port": int(d.nHttpPort or 0),
                    "port": int(d.nPort or 0),
                    "dhcp": bool(d.bDhcpEn),
                    "subnet_mask": _decode(d.szSubmask),
                    "gateway": _decode(d.szGateway),
                    "init_status": init,
                    "needs_activation": init == INIT_PENDING,
                    "pwd_reset_way": int(d.byPwdResetWay or 0),
                    "needs_phone": bool(d.byPwdResetWay & RESET_PHONE),
                    "needs_email": bool(d.byPwdResetWay & RESET_EMAIL),
                }
            except Exception:
                # Nunca deixar excecao subir pra dentro do SDK (seria segfault).
                pass

        cb = _SEARCH_CB(on_found)
        info = DEVICE_IP_SEARCH_INFO()
        info.dwSize = ctypes.sizeof(DEVICE_IP_SEARCH_INFO)
        info.nIpNum = len(alvos)
        for i, ip in enumerate(alvos):
            raw = ip.encode()[:63]
            ctypes.memmove(info.szIP[i], raw, len(raw))

        ok = lib.CLIENT_SearchDevicesByIPs(ctypes.byref(info), cb, 0, None, c_uint(wait_ms))
        # A chamada retorna na hora; os callbacks chegam durante a janela.
        time.sleep(wait_ms / 1000.0 + 1.0)

        return {
            "ok": bool(ok),
            "scanned": len(alvos),
            "devices": sorted(achados.values(), key=lambda r: r.get("ip") or ""),
            "error": "" if ok else _last_error(lib),
        }


def init_device(
    device_ip: str,
    mac: str,
    password: str,
    username: str = "admin",
    email: str = "",
    phone: str = "",
    pwd_reset_way: int = 0,
    wait_ms: int = 8000,
) -> Dict[str, Any]:
    """Cria a conta admin numa camera de fabrica (`CLIENT_InitDevAccountByIP`).

    `device_ip` e o IP **virtual** (vnat) e `mac` tem que ser o MAC que a busca
    devolveu -- o SDK casa os dois, e MAC errado faz o device ignorar calado.

    O dado de recuperacao nao e enfeite: quando `pwd_reset_way` pede email (as
    VIPC-1230-B-G2 pedem), mandar vazio faz o init falhar.
    """
    ip = _text(device_ip)
    mac_n = _text(mac)
    pwd = str(password or "")
    if not ip or not mac_n or not pwd:
        return {"ok": False, "error": "ip, mac e senha sao obrigatorios"}

    way = int(pwd_reset_way or 0)
    if (way & RESET_PHONE) and not _text(phone):
        return {"ok": False, "error": "esta camera exige celular de recuperacao"}
    if (way & RESET_EMAIL) and not _text(email):
        return {"ok": False, "error": "esta camera exige email de recuperacao"}

    with _lock:
        lib = _load()
        if not lib:
            return {"ok": False, "error": _load_error}

        entrada = NET_IN_INIT_DEVICE_ACCOUNT()
        entrada.dwSize = ctypes.sizeof(NET_IN_INIT_DEVICE_ACCOUNT)
        entrada.szMac = mac_n.encode()[:39]
        entrada.szUserName = (_text(username) or "admin").encode()[:127]
        entrada.szPwd = pwd.encode()[:127]
        entrada.byPwdResetWay = way
        if way & RESET_PHONE:
            entrada.szCellPhone = _text(phone).encode()[:31]
        if way & RESET_EMAIL:
            entrada.szMail = _text(email).encode()[:63]

        saida = NET_OUT_INIT_DEVICE_ACCOUNT()
        saida.dwSize = ctypes.sizeof(NET_OUT_INIT_DEVICE_ACCOUNT)

        ok = lib.CLIENT_InitDevAccountByIP(
            ctypes.byref(entrada), ctypes.byref(saida),
            c_uint(wait_ms), None, c_char_p(ip.encode()),
        )
        if not ok:
            return {"ok": False, "error": f"CLIENT_InitDevAccountByIP falhou ({_last_error(lib)})"}
        return {"ok": True, "ip": ip, "mac": mac_n, "username": _text(username) or "admin"}
