# -*- coding: utf-8 -*-
"""Vincular, trocar e soltar camera no canal do gravador Intelbras, pelo NetSDK.

POR QUE O SDK, E NAO HTTP
-------------------------
O caminho HTTP `/cgi-bin/api/LogicDeviceManager/<acao>` NAO EXISTE no firmware
do NVD 1408 (4.001.00IB000.0.R). Ele devolve "HTTP 400: Error Bad Request!" --
exatamente a mesma resposta que uma URL inventada, o que foi como se descobriu:

    /cgi-bin/api/LogicDeviceManager/naoExisteIsto  -> 400 Bad Request
    /cgi-bin/api/LogicDeviceManager/getCameraAll   -> 400 Bad Request   (leitura!)
    /cgi-bin/LogicDeviceManager.cgi?action=getCameraAll -> 200

Ou seja, o 400 nunca foi sobre o canal nem sobre o corpo enviado: era a URL. O
que o equipamento expoe e a API de CONFIGURACAO, e nela a camera remota e
identificada por um DeviceID (`uuid:System_CONFIG_NETCAMERA_INFO_<n>`), nao por
um indice numerico.

Dava para escrever por `configManager.cgi?action=setConfig&...`, mas ai a senha
da camera viaja NA URL e cai no log de acesso do gravador. O NetSDK ja esta na
imagem (/opt/netsdk) e leva tudo no corpo da sessao.

COMO O EQUIPAMENTO ORGANIZA OS CANAIS
-------------------------------------
Os 8 canais sao entradas FIXAS da tabela RemoteDevice -- as livres existem o
tempo todo, so que desligadas:

    INFO_0  Enable=true   Address=100.65.8.11    (canal 01, em uso)
    ...
    INFO_6  Enable=false  Address=192.168.0.0    (canal 07, livre)

Por isso vincular, trocar e soltar sao A MESMA operacao: alterar a entrada
INFO_<canal-1>. O sufixo bate com o UniqueChannel, conferido no equipamento.

SOBRE A SENHA DAS OUTRAS CAMERAS
--------------------------------
A leitura devolve `"Password": "******"` -- mascarado. Se a tabela inteira fosse
devolvida ao gravador, as outras cameras receberiam a string "******" como senha
e o site inteiro cairia. Por isso aqui so se envia A ENTRADA ALTERADA.

Isolamento: o SDK ja derrubou o processo da API com segfault (exit 139), entao
toda chamada roda em subprocesso -- mesmo padrao de `intelbras_netsdk`.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from ctypes import (Structure, byref, c_char, c_int, c_longlong, c_uint,
                    c_ushort, create_string_buffer)
from typing import Any, Dict

LIB = os.path.join(os.getenv("NETSDK_LIB_DIR", "/opt/netsdk/lib"), "libdhnetsdk.so")
PORTA_SDK = 37777
_VAZIO = "192.168.0.0"   # o que o proprio equipamento poe num canal livre


class DEVINFO(Structure):
    _fields_ = [("sSerialNumber", c_char * 48), ("nAlarmInPortNum", c_int),
                ("nAlarmOutPortNum", c_int), ("nDiskNum", c_int), ("nDVRType", c_int),
                ("nChanNum", c_int), ("byLimitLoginTime", ctypes.c_ubyte),
                ("byLeftLogTimes", ctypes.c_ubyte), ("bReserved", ctypes.c_ubyte * 2),
                ("nLockLeftTime", c_int), ("Reserved", c_char * 4)]


def _uuid(canal: int) -> str:
    return "uuid:System_CONFIG_NETCAMERA_INFO_%d" % (int(canal) - 1)


def _carregar():
    lib = ctypes.CDLL(LIB)
    lib.CLIENT_Init.restype = ctypes.c_bool
    lib.CLIENT_LoginEx2.restype = c_longlong
    lib.CLIENT_GetLastError.restype = c_uint
    lib.CLIENT_GetNewDevConfig.restype = ctypes.c_bool
    lib.CLIENT_SetNewDevConfig.restype = ctypes.c_bool
    if not lib.CLIENT_Init(None, 0):
        raise RuntimeError("CLIENT_Init falhou")
    return lib


def _entrar(lib, ip: str, user: str, senha: str, porta: int):
    info = DEVINFO()
    erro = c_int(0)
    h = lib.CLIENT_LoginEx2(ip.encode(), c_ushort(int(porta)), user.encode(),
                            senha.encode(), c_int(0), None, byref(info), byref(erro))
    if not h:
        # O codigo do SDK nao diz nada a quem esta no poste; traduz.
        mapa = {1: "usuario ou senha do gravador nao conferem",
                2: "usuario ou senha do gravador nao conferem",
                3: "o gravador nao respondeu na porta %d" % porta,
                4: "o gravador nao respondeu na porta %d" % porta,
                5: "esse usuario ja esta logado no gravador",
                7: "o gravador esta sem rede"}
        raise RuntimeError(mapa.get(erro.value,
                                    "o gravador recusou a conexao (codigo %d)" % erro.value))
    return h


def _ler_tabela(lib, h) -> Dict[str, Any]:
    buf = create_string_buffer(512 * 1024)
    erro = c_int(0)
    ok = lib.CLIENT_GetNewDevConfig(c_longlong(h), b"RemoteDevice", c_int(-1),
                                    buf, c_uint(len(buf)), byref(erro), c_int(10000))
    if not ok:
        raise RuntimeError("nao consegui ler os canais do gravador (codigo %d)" % erro.value)
    dados = json.loads(buf.value.decode("utf-8", "replace") or "{}")
    return (dados.get("params") or {}).get("table") or {}


def _gravar_entrada(lib, h, chave: str, entrada: Dict[str, Any]) -> None:
    # SEM o embrulho {"table": ...}. A leitura devolve params.table, mas a
    # escrita quer a tabela crua. Com o embrulho o equipamento responde OK,
    # erro 0, e NAO APLICA nada -- medido no NVD 1516 (fw 4.000.00IB001.0.T)
    # em 06/10/2026: o formato com "table" deixou o canal 01 como estava, o
    # formato cru o liberou na hora. Era o "Gravador atualizado" sem efeito.
    corpo = json.dumps({chave: entrada}).encode()
    erro, reiniciar = c_int(0), c_int(0)
    ok = lib.CLIENT_SetNewDevConfig(c_longlong(h), b"RemoteDevice", c_int(-1),
                                    corpo, c_uint(len(corpo)),
                                    byref(erro), byref(reiniciar), c_int(10000))
    if not ok:
        raise RuntimeError("o gravador recusou a alteracao (codigo %d)" % erro.value)


def _agir(p: Dict[str, Any]) -> Dict[str, Any]:
    lib = _carregar()
    h = None
    try:
        h = _entrar(lib, p["ip_alcance"], p["user"], p["senha"],
                    int(p.get("porta") or PORTA_SDK))
        tabela = _ler_tabela(lib, h)
        acao = p.get("acao")

        if acao == "ler":
            canais = []
            for chave, e in sorted(tabela.items()):
                try:
                    n = int(chave.rsplit("_", 1)[-1]) + 1
                except Exception:
                    continue
                vi = (e.get("VideoInputs") or [{}])[0]
                livre = not e.get("Enable") or str(e.get("Address") or "") in ("", _VAZIO)
                canais.append({"canal": n, "livre": livre,
                               "ip": "" if livre else e.get("Address", ""),
                               "nome": vi.get("Name", ""), "mac": e.get("Mac", ""),
                               "modelo": e.get("DeviceType", ""),
                               "protocolo": e.get("ProtocolType", "")})
            return {"ok": True, "canais": canais}

        chave = _uuid(p["canal"])
        if chave not in tabela:
            return {"ok": False, "error": "o canal %s nao existe nesse gravador" % p["canal"]}
        # Parte-se da entrada que esta la: assim os campos que ninguem pediu
        # para mudar continuam como o equipamento os tinha.
        e = dict(tabela[chave])

        if acao == "soltar":
            e.update({"Enable": False, "Address": _VAZIO, "UserName": "", "Password": ""})
            e["VideoInputs"] = [dict(v, Name="") for v in (e.get("VideoInputs") or [{}])]
        else:
            e.update({"Enable": True, "Address": p["cam_ip"],
                      "UserName": p["cam_user"], "Password": p["cam_senha"],
                      "ProtocolType": p.get("protocolo") or "Private",
                      "Port": int(p.get("porta_cam") or 37777),
                      "HttpPort": int(p.get("porta_http") or 80)})
            if p.get("porta_rtsp"):
                e["RtspPort"] = int(p["porta_rtsp"])
            if str(p.get("protocolo") or "").lower() == "onvif":
                # Igual a entrada que o proprio NVD grava ao cadastrar ONVIF na
                # mao (canal 22 do NVD 1232 da SIERRA): Vendor "Onvif" e RTSP 554.
                # Partindo de um canal livre, Vendor ficava "Private".
                e["Vendor"] = "Onvif"
                if not p.get("porta_rtsp"):
                    e["RtspPort"] = 554
                # Canal livre do NVD 1516 trazia HttpsPort=80; o cadastro manual grava 443.
                if int(e.get("HttpsPort") or 0) in (0, 80):
                    e["HttpsPort"] = 443
            if p.get("nome"):
                vis = e.get("VideoInputs") or [{}]
                e["VideoInputs"] = [dict(vis[0], Name=p["nome"])] + list(vis[1:])

        _gravar_entrada(lib, h, chave, e)
        # O OK do SDK nao prova nada (ver _gravar_entrada): so vale o que o
        # equipamento devolve na releitura.
        lido = _ler_tabela(lib, h).get(chave) or {}
        if acao == "soltar":
            aplicou = (not lido.get("Enable")) or str(lido.get("Address") or "") in ("", _VAZIO)
        else:
            aplicou = bool(lido.get("Enable")) and str(lido.get("Address") or "") == str(p["cam_ip"])
        if not aplicou:
            return {"ok": False, "canal": int(p["canal"]),
                    "error": "o gravador aceitou o comando mas o canal nao mudou -- nada foi alterado"}
        return {"ok": True, "canal": int(p["canal"]), "acao": acao}
    finally:
        if h:
            try:
                lib.CLIENT_Logout(c_longlong(h))
            except Exception:
                pass
        try:
            lib.CLIENT_Cleanup()
        except Exception:
            pass


# --------------------------------------------------------------- isolamento
def _em_subprocesso(pedido: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
    try:
        r = subprocess.run([sys.executable, "-m", "app.services.intelbras_canal_sdk"],
                           input=json.dumps(pedido), capture_output=True, text=True,
                           timeout=timeout, cwd="/app")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "o gravador nao respondeu a tempo -- nada foi alterado"}
    # O SDK escreve em stdout por conta propria; a resposta e a ULTIMA linha.
    for linha in reversed((r.stdout or "").strip().splitlines()):
        try:
            return json.loads(linha)
        except Exception:
            continue
    if r.returncode and r.returncode < 0:
        return {"ok": False,
                "error": "o SDK da Intelbras quebrou (sinal %d) -- "
                         "nada foi alterado no equipamento" % -r.returncode}
    return {"ok": False, "error": (r.stderr or "o SDK nao respondeu nada").strip()[:300]}


def _alcance(host: str, connector_id: str) -> str:
    from app.services import connector_routing_vnat as _vnat
    if connector_id:
        try:
            _vnat.set_olt_reach_connector(connector_id)
        except Exception:
            pass
    return _vnat.reach_olt_ip(host) or host


def ler_canais(host, user, senha, connector_id="", porta=PORTA_SDK):
    return _em_subprocesso({"acao": "ler", "ip_alcance": _alcance(host, connector_id),
                            "user": user, "senha": senha, "porta": porta})


def gravar_canal(host, user, senha, canal, cam_ip, cam_user, cam_senha,
                 connector_id="", nome="", protocolo="", porta=PORTA_SDK,
                 porta_cam=None, porta_http=None, porta_rtsp=None):
    return _em_subprocesso({"acao": "gravar", "ip_alcance": _alcance(host, connector_id),
                            "user": user, "senha": senha, "porta": porta, "canal": canal,
                            "cam_ip": cam_ip, "cam_user": cam_user, "cam_senha": cam_senha,
                            "nome": nome, "protocolo": protocolo, "porta_cam": porta_cam,
                            "porta_http": porta_http, "porta_rtsp": porta_rtsp})


def soltar_canal(host, user, senha, canal, connector_id="", porta=PORTA_SDK):
    return _em_subprocesso({"acao": "soltar", "ip_alcance": _alcance(host, connector_id),
                            "user": user, "senha": senha, "porta": porta, "canal": canal})


if __name__ == "__main__":
    try:
        resposta = _agir(json.loads(sys.stdin.read() or "{}"))
    except Exception as exc:
        resposta = {"ok": False, "error": str(exc)[:300]}
    print(json.dumps(resposta, ensure_ascii=False))
