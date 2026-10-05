"""HCNetSDK da Hikvision (libhcnetsdk.so) pelo ctypes, so para ATIVAR camera.

Por que SDK e nao HTTP: uma Hikvision de fabrica recusa
`PUT /ISAPI/System/activate` com a senha em texto (`badParameters`). O
equipamento exige um handshake -- o proprio bundle da camera mostra o caminho:
o cliente gera um par RSA, manda a publica em `POST /ISAPI/Security/challenge`,
decifra o segredo que volta e manda a senha cifrada em AES com ele. O
`NET_DVR_ActivateDevice` faz tudo isso por dentro, recebendo a senha em texto.

Confirmado no header V6.1.9.4:

    NET_DVR_ActivateDevice(char* sDVRIP, WORD wDVRPort, LPNET_DVR_ACTIVATECFG)
    NET_DVR_ACTIVATECFG { DWORD dwSize; BYTE sPassword[16]; BYTE byLoginMode; BYTE byHttps; BYTE byRes[106]; }

E por IP+porta (unicast), entao **atravessa o tunel do conector** igual ao
NetSDK da Intelbras -- nada aqui depende de broadcast/SADP, que nao passa.

ISOLAMENTO: erro dentro de uma lib C nao vira excecao Python, vira segfault, e
mataria o processo inteiro da API -- todos os clientes. Por isso o modulo
tambem roda como programa (`python -m app.services.hikvision_netsdk`) e quem
chama de fora usa `ativar_isolado()`, que o executa em subprocesso. Se estourar,
morre so o subprocesso.

A lib nao vem no repo. O Dockerfile copia de `deploy/hiksdk/` para
`HIKSDK_LIB_DIR`; sem ela o modulo carrega normal e `available()` da False.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from ctypes import Structure, c_byte, c_char, c_uint, c_ushort
from typing import Any, Dict

LIB_DIR = os.getenv("HIKSDK_LIB_DIR", "/opt/hiksdk/lib")
LIB_NAME = "libhcnetsdk.so"

# Ordem importa: o loader precisa destas abertas com RTLD_GLOBAL antes da
# principal, senao ela nao acha os simbolos.
DEPENDENCIAS = ("libcrypto.so.1.1", "libssl.so.1.1", "libz.so", "libhpr.so",
                "libHCCore.so")

PASSWD_LEN = 16          # do header -- senha de ativacao cabe em 15 + terminador
CFG_SDK_PATH = 2         # NET_SDK_INIT_CFG_SDK_PATH

LOGIN_PRIVADO = 0        # porta 8000
LOGIN_ISAPI = 1          # porta 80

ERRO_JA_ATIVADA = 252    # NET_DVR_ERROR_DEVICE_HAS_ACTIVATED
ERRO_NAO_ATIVADA = 250   # NET_DVR_ERROR_DEVICE_NOT_ACTIVATED

_sdk = None


class NET_DVR_LOCAL_SDK_PATH(Structure):
    _fields_ = [("sPath", c_char * 256), ("byRes", c_byte * 128)]


class NET_DVR_ACTIVATECFG(Structure):
    """Espelho de HCNetSDK.h. Tamanho e ordem importam byte a byte."""

    _fields_ = [
        ("dwSize", c_uint),
        ("sPassword", c_char * PASSWD_LEN),
        ("byLoginMode", c_byte),
        ("byHttps", c_byte),
        ("byRes", c_byte * 106),
    ]


MAX_PERGUNTAS = 32       # NET_SDK_MAX_QUESTION_LIST_LEN
TAM_RESPOSTA = 256       # NET_SDK_MAX_ANSWER_LEN
TAM_SENHA_LOGIN = 128    # NET_SDK_MAX_LOGIN_PASSWORD_LEN
CMD_SET_PERGUNTAS = 4366  # NET_DVR_SET_SECURITY_QUESTION_CFG


class NET_DVR_USER_LOGIN_INFO(Structure):
    _fields_ = [
        ("sDeviceAddress", c_char * 129),
        ("byUseTransport", c_byte),
        ("wPort", c_ushort),
        ("sUserName", c_char * 64),
        ("sPassword", c_char * 64),
        ("cbLoginResult", ctypes.c_void_p),
        ("pUser", ctypes.c_void_p),
        ("bUseAsynLogin", ctypes.c_int),
        ("byProxyType", c_byte),
        ("byUseUTCTime", c_byte),
        ("byLoginMode", c_byte),
        ("byHttps", c_byte),
        ("iProxyID", ctypes.c_long),
        ("byVerifyMode", c_byte),
        ("byRes3", c_byte * 119),
    ]


class NET_DVR_SINGLE_SECURITY_QUESTION_CFG(Structure):
    _fields_ = [
        ("dwSize", c_uint),
        ("dwId", c_uint),
        ("sAnswer", c_char * TAM_RESPOSTA),
        ("byMark", c_byte),
        ("byRes", c_byte * 127),
    ]


class NET_DVR_SECURITY_QUESTION_CFG(Structure):
    _fields_ = [
        ("dwSize", c_uint),
        ("struSecurityQuestion", NET_DVR_SINGLE_SECURITY_QUESTION_CFG * MAX_PERGUNTAS),
        ("sLoginPassWord", c_char * TAM_SENHA_LOGIN),
        ("byRes", c_byte * 512),
    ]


def _carregar():
    """Abre a lib uma vez por processo. Devolve None se o SDK nao esta instalado."""
    global _sdk
    if _sdk is not None:
        return _sdk
    principal = os.path.join(LIB_DIR, LIB_NAME)
    if not os.path.exists(principal):
        return None
    for dep in DEPENDENCIAS:
        caminho = os.path.join(LIB_DIR, dep)
        if os.path.exists(caminho):
            ctypes.CDLL(caminho, mode=ctypes.RTLD_GLOBAL)
    sdk = ctypes.CDLL(principal)

    # Sem isto o SDK procura os plugins de HCNetSDKCom no diretorio corrente.
    caminho = NET_DVR_LOCAL_SDK_PATH()
    caminho.sPath = LIB_DIR.encode()
    sdk.NET_DVR_SetSDKInitCfg(CFG_SDK_PATH, ctypes.byref(caminho))
    sdk.NET_DVR_Init()
    sdk.NET_DVR_ActivateDevice.restype = ctypes.c_bool
    sdk.NET_DVR_ActivateDevice.argtypes = [
        ctypes.c_char_p, c_ushort, ctypes.POINTER(NET_DVR_ACTIVATECFG)]
    _sdk = sdk
    return _sdk


def available() -> bool:
    try:
        return _carregar() is not None
    except Exception:
        return False


def ativar(ip: str, senha: str, porta: int = 8000,
           modo: int = LOGIN_PRIVADO) -> Dict[str, Any]:
    """Cria a conta admin numa camera de fabrica. Roda NO PROCESSO atual --
    quem chama de fora deve usar `ativar_isolado`."""
    if len(senha.encode()) >= PASSWD_LEN:
        return {"ok": False,
                "error": f"a senha nao pode passar de {PASSWD_LEN - 1} caracteres "
                         "(limite do proprio SDK da Hikvision)"}
    sdk = _carregar()
    if sdk is None:
        return {"ok": False, "error": "o SDK da Hikvision nao esta instalado no servidor"}

    cfg = NET_DVR_ACTIVATECFG()
    cfg.dwSize = ctypes.sizeof(NET_DVR_ACTIVATECFG)
    cfg.sPassword = senha.encode()
    cfg.byLoginMode = modo
    cfg.byHttps = 0

    ok = bool(sdk.NET_DVR_ActivateDevice(ip.encode(), c_ushort(int(porta)),
                                         ctypes.byref(cfg)))
    if ok:
        return {"ok": True, "usuario": "admin"}

    codigo = int(sdk.NET_DVR_GetLastError())
    if codigo == ERRO_JA_ATIVADA:
        return {"ok": False, "ja_ativada": True,
                "error": "essa camera ja estava ativada"}
    return {"ok": False, "codigo": codigo,
            "error": f"o SDK recusou a ativacao (erro {codigo})"}


# As perguntas de recuperacao NAO ficam aqui: este modelo (IPC-B121H-C,
# V5.8.10) nao suporta os comandos 4363/4364/4365/4366 do SDK -- ate a LEITURA
# devolve 17 (PARAMETER_ERROR), o que descarta erro de struct. Elas sao gravadas
# por ISAPI, em `hikvision_activation.definir_perguntas`.


def _em_subprocesso(pedido: Dict[str, Any], timeout: float = 90.0) -> Dict[str, Any]:
    """Roda uma acao do SDK em outro processo -- segfault nao leva a API junto."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "app.services.hikvision_netsdk"],
            input=json.dumps(pedido), capture_output=True, text=True,
            timeout=timeout, cwd="/app",
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "a operacao passou do tempo e foi cancelada"}
    for linha in reversed((r.stdout or "").strip().splitlines()):
        try:
            return json.loads(linha)
        except Exception:
            continue
    if r.returncode and r.returncode < 0:
        return {"ok": False,
                "error": f"o SDK quebrou (sinal {-r.returncode}) -- nada foi alterado"}
    return {"ok": False, "error": (r.stderr or "o SDK nao respondeu nada").strip()[:300]}


def ativar_isolado(ip: str, senha: str, porta: int = 8000,
                   modo: int = LOGIN_PRIVADO, timeout: float = 90.0) -> Dict[str, Any]:
    """Mesma coisa, em subprocesso -- um segfault na lib C nao leva a API junto."""
    return _em_subprocesso(
        {"acao": "ativar", "ip": ip, "senha": senha, "porta": porta, "modo": modo},
        timeout=timeout)


if __name__ == "__main__":
    # O SDK escreve coisas na saida padrao; por isso a resposta vai na ULTIMA
    # linha, e quem le procura de tras para frente.
    try:
        pedido = json.loads(sys.stdin.read() or "{}")
        resposta = ativar(
            str(pedido.get("ip") or ""), str(pedido.get("senha") or ""),
            int(pedido.get("porta") or 8000), int(pedido.get("modo") or 0),
        )
    except Exception as exc:
        resposta = {"ok": False, "error": f"falha no worker do SDK: {exc}"}
    print(json.dumps(resposta))
