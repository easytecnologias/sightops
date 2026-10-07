"""Escrita no gravador: adicionar, editar, excluir e renomear canal.

Duas APIs, mesma ideia:
  Intelbras  LogicDeviceManager (POST, JSON no corpo)
  Hikvision  ISAPI InputProxy   (POST/PUT/DELETE, XML no corpo)

O codigo antigo usava `configManager.cgi?action=setConfig&RemoteDevice[N].Password=...`
-- um GET com a senha da camera NA URL, que entra no log de acesso do gravador,
e sucesso adivinhado procurando a palavra "error" no texto da resposta. Aqui a
senha vai no corpo e a confirmacao vem do `failedCode` que o proprio
equipamento devolve.

Caminho de escrita provado em 30/09/2026 nos dois gravadores de Perucaba,
regravando o valor que ja estava la (nada mudou).
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, Tuple
from urllib.parse import quote

import requests
import urllib3
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from app.services import connector_routing_vnat as _vnat
from app.services.recorder_xray import detectar_marca

urllib3.disable_warnings()

NS = {"h": "http://www.hikvision.com/ver20/XMLSchema"}
_TEMPO = 20.0


class ErroGravador(Exception):
    """Falha que o tecnico precisa ler: ja vem em linguagem de operacao."""


def _req(metodo: str, url: str, user: str, password: str,
         corpo: Any = None, tipo: str = "application/xml",
         timeout: float = _TEMPO) -> Tuple[int | None, str]:
    cabecalho = {"Content-Type": tipo} if corpo is not None else None
    for auth in (HTTPDigestAuth(user, password), HTTPBasicAuth(user, password)):
        try:
            r = requests.request(metodo, url, auth=auth, timeout=timeout, verify=False,
                                 data=corpo, headers=cabecalho)
            if r.status_code not in (401, 403):
                return r.status_code, (r.text or "")
        except Exception as exc:
            raise ErroGravador(f"nao consegui falar com o gravador: {exc}") from exc
    raise ErroGravador("o gravador recusou usuario ou senha")


def _base(host: str, porta: Any, connector_id: str = "") -> str:
    if connector_id:
        try:
            _vnat.set_olt_reach_connector(connector_id)
        except Exception:
            pass
    alcance = _vnat.reach_olt_ip(host) or host
    try:
        p = int(porta or 80)
    except Exception:
        p = 80
    return f"http://{alcance}" + ("" if p == 80 else f":{p}")


# ------------------------------------------------------------------ Intelbras
def _intelbras_falhou(corpo: str) -> str:
    """Le o failedCode do proprio equipamento em vez de procurar "error" no texto."""
    try:
        dados = json.loads(corpo or "{}")
    except Exception:
        baixo = (corpo or "").lower()
        if "ok" in baixo and "error" not in baixo:
            return ""
        return (corpo or "sem resposta").strip()[:160]
    for grupo in (dados.get("group") or []):
        for cam in (grupo.get("cameras") or []):
            codigo = int(cam.get("failedCode") or 0)
            if codigo:
                return {1: "o canal nao aceita configuracao"}.get(
                    codigo, f"o gravador recusou (codigo {codigo})")
    for info in (dados.get("info") or []):
        codigo = int(info.get("failedCode") or 0)
        if codigo:
            return f"o gravador recusou (codigo {codigo})"
    return ""


def _intelbras_corpo(canal: int, ip: str, user: str, senha: str,
                     protocolo: str, porta: Any, porta_http: Any, porta_rtsp: Any) -> str:
    return json.dumps({"group": [{
        "DeviceInfo": {
            "UserName": user, "Password": senha,
            "ProtocolType": protocolo or "Private",
            "Address": ip,
            "Port": int(porta or 37777),
            "HttpPort": int(porta_http or 80),
            "RtspPort": int(porta_rtsp or 554),
        },
        # BASE 0. Conferido no proprio equipamento (NVD 1408, firmware
        # 4.001.00IB000.0.R): o getCameraAll devolve
        #     camera[0].UniqueChannel=0   -> canal 01 da tela
        #     camera[1].UniqueChannel=1   -> canal 02 da tela
        # Mandando o numero da tela, a acao caia sempre UM CANAL ADIANTE: pedir
        # o canal 7 escrevia no 8. O renomear logo abaixo ja descontava 1, e o
        # vinculo do assistente CFTV tambem (idx = channel - 1 em
        # deployments.py) -- so estas duas chamadas ficaram para tras.
        "cameras": [{"uniqueChannel": int(canal) - 1}],
    }]})


def _intelbras_add(base, user, password, **k) -> Dict[str, Any]:
    corpo = _intelbras_corpo(k["canal"], k["ip"], k["cam_user"], k["cam_senha"],
                             k.get("protocolo"), k.get("porta"), k.get("porta_http"),
                             k.get("porta_rtsp"))
    cod, txt = _req("POST", f"{base}/cgi-bin/api/LogicDeviceManager/addCameraByGroup",
                    user, password, corpo, "application/json")
    erro = _intelbras_falhou(txt) if cod and 200 <= cod < 300 else f"HTTP {cod}: {txt[:120]}"
    if erro:
        raise ErroGravador(erro)
    return {"comando": "addCameraByGroup", "resposta": txt[:200]}


def _intelbras_editar(base, user, password, **k) -> Dict[str, Any]:
    # setCamera troca os dados SEM soltar o canal -- e o que se usa quando a
    # camera muda de IP ou de senha e o vinculo deve continuar.
    corpo = _intelbras_corpo(k["canal"], k["ip"], k["cam_user"], k["cam_senha"],
                             k.get("protocolo"), k.get("porta"), k.get("porta_http"),
                             k.get("porta_rtsp"))
    cod, txt = _req("POST", f"{base}/cgi-bin/api/LogicDeviceManager/setCamera",
                    user, password, corpo, "application/json")
    erro = _intelbras_falhou(txt) if cod and 200 <= cod < 300 else f"HTTP {cod}: {txt[:120]}"
    if erro:
        raise ErroGravador(erro)
    return {"comando": "setCamera", "resposta": txt[:200]}


def _intelbras_excluir(base, user, password, canal: int, **_) -> Dict[str, Any]:
    # O canal precisa existir para ser solto. Sem esta checagem o equipamento
    # responde "HTTP 400: Error Bad Request!", que nao diz nada a quem esta no
    # campo.
    # Mesma base 0 do addCameraByGroup. Aqui o erro era o mais caro dos tres:
    # "soltar o canal 1" apontava para o identificador do canal 2.
    corpo = json.dumps({"group": [{"uniqueChannels": [int(canal) - 1]}]})
    cod, txt = _req("POST", f"{base}/cgi-bin/api/LogicDeviceManager/deleteCameraByGroup",
                    user, password, corpo, "application/json")
    erro = _intelbras_falhou(txt) if cod and 200 <= cod < 300 else f"HTTP {cod}: {txt[:120]}"
    if erro:
        raise ErroGravador(erro)
    return {"comando": "deleteCameraByGroup", "resposta": txt[:200]}


def _intelbras_renomear(base, user, password, canal: int, nome: str, **_) -> Dict[str, Any]:
    # ChannelTitle e indexado em 0; o canal 1 e o indice 0.
    url = (f"{base}/cgi-bin/configManager.cgi?action=setConfig"
           f"&ChannelTitle[{int(canal) - 1}].Name={quote(nome)}")
    cod, txt = _req("GET", url, user, password)
    if not (cod and 200 <= cod < 300) or "error" in (txt or "").lower():
        raise ErroGravador(f"o gravador recusou o novo nome: {txt[:120]}")
    return {"comando": "setConfig ChannelTitle", "resposta": (txt or "").strip()[:80]}


# ------------------------------------------------------------------ Hikvision
def _hik_erro(corpo: str) -> str:
    try:
        raiz = ET.fromstring(corpo or "")
    except Exception:
        return ""
    estado = (raiz.findtext("h:statusString", "", NS) or "").strip()
    sub = (raiz.findtext("h:subStatusCode", "", NS) or "").strip()
    if estado.lower() in ("ok", "success", ""):
        return ""
    return f"{estado}{(' · ' + sub) if sub else ''}"


def _hik_xml(canal: int, ip: str, user: str, senha: str, nome: str,
             protocolo: str, porta: Any) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<InputProxyChannel xmlns="http://www.hikvision.com/ver20/XMLSchema">'
        f"<id>{int(canal)}</id>"
        f"<name>{nome}</name>"
        "<sourceInputPortDescriptor>"
        f"<proxyProtocol>{protocolo or 'ONVIF'}</proxyProtocol>"
        "<addressingFormatType>ipaddress</addressingFormatType>"
        f"<ipAddress>{ip}</ipAddress>"
        f"<managePortNo>{int(porta or 80)}</managePortNo>"
        "<srcInputPort>1</srcInputPort>"
        f"<userName>{user}</userName>"
        f"<password>{senha}</password>"
        "<streamType>auto</streamType>"
        "</sourceInputPortDescriptor>"
        "</InputProxyChannel>"
    )


def _hik_add(base, user, password, **k) -> Dict[str, Any]:
    # HIKVISION fala com camera Hikvision (porta de gerencia 8000); ONVIF cobre
    # as outras marcas (porta 80). Tenta os dois, nessa ordem.
    ultimo = ""
    for protocolo, porta in (("HIKVISION", 8000), ("ONVIF", 80)):
        corpo = _hik_xml(k["canal"], k["ip"], k["cam_user"], k["cam_senha"],
                         k.get("nome") or "", protocolo, k.get("porta") or porta)
        for metodo, url in (("PUT", f"{base}/ISAPI/ContentMgmt/InputProxy/channels/{int(k['canal'])}"),
                            ("POST", f"{base}/ISAPI/ContentMgmt/InputProxy/channels")):
            cod, txt = _req(metodo, url, user, password, corpo.encode("utf-8"))
            if cod and 200 <= cod < 300 and not _hik_erro(txt):
                return {"comando": f"{metodo} InputProxy ({protocolo})", "resposta": txt[:200]}
            ultimo = _hik_erro(txt) or f"HTTP {cod}"
    raise ErroGravador(f"o gravador nao aceitou a camera: {ultimo}")


def _hik_editar(base, user, password, **k) -> Dict[str, Any]:
    corpo = _hik_xml(k["canal"], k["ip"], k["cam_user"], k["cam_senha"],
                     k.get("nome") or "", k.get("protocolo") or "ONVIF",
                     k.get("porta") or 80)
    url = f"{base}/ISAPI/ContentMgmt/InputProxy/channels/{int(k['canal'])}"
    cod, txt = _req("PUT", url, user, password, corpo.encode("utf-8"))
    erro = _hik_erro(txt) if cod and 200 <= cod < 300 else f"HTTP {cod}: {txt[:120]}"
    if erro:
        raise ErroGravador(erro)
    return {"comando": "PUT InputProxy", "resposta": txt[:200]}


def _hik_excluir(base, user, password, canal: int, **_) -> Dict[str, Any]:
    url = f"{base}/ISAPI/ContentMgmt/InputProxy/channels/{int(canal)}"
    cod, txt = _req("DELETE", url, user, password)
    erro = _hik_erro(txt) if cod and 200 <= cod < 300 else f"HTTP {cod}: {txt[:120]}"
    if erro:
        raise ErroGravador(erro)
    return {"comando": "DELETE InputProxy", "resposta": txt[:200]}


def _hik_renomear(base, user, password, canal: int, nome: str, **_) -> Dict[str, Any]:
    """Renomear exige devolver o canal inteiro: PUT com so o <name> apaga o resto."""
    url = f"{base}/ISAPI/ContentMgmt/InputProxy/channels/{int(canal)}"
    cod, atual = _req("GET", url, user, password)
    if not (cod and 200 <= cod < 300 and atual):
        raise ErroGravador("nao consegui ler o canal antes de renomear")
    novo = re.sub(r"<name>[^<]*</name>", f"<name>{nome}</name>", atual, count=1)
    if novo == atual and "<name>" not in atual:
        novo = atual.replace("<sourceInputPortDescriptor>",
                             f"<name>{nome}</name><sourceInputPortDescriptor>", 1)
    cod, txt = _req("PUT", url, user, password, novo.encode("utf-8"))
    erro = _hik_erro(txt) if cod and 200 <= cod < 300 else f"HTTP {cod}: {txt[:120]}"
    if erro:
        raise ErroGravador(erro)
    return {"comando": "PUT InputProxy (nome)", "resposta": txt[:200]}


# ------------------------------------------------------------------ fachada
_ACOES = {
    "intelbras": {"adicionar": _intelbras_add, "editar": _intelbras_editar,
                  "excluir": _intelbras_excluir, "renomear": _intelbras_renomear},
    "hikvision": {"adicionar": _hik_add, "editar": _hik_editar,
                  "excluir": _hik_excluir, "renomear": _hik_renomear},
}


def executar(acao: str, *, host: str, user: str, password: str, canal: int,
             porta_gravador: Any = None, connector_id: str = "",
             ip: str = "", cam_user: str = "", cam_senha: str = "", nome: str = "",
             protocolo: str = "", porta: Any = None, porta_http: Any = None,
             porta_rtsp: Any = None) -> Dict[str, Any]:
    """Executa a acao no gravador e devolve o que foi feito.

    acao: "adicionar" | "editar" | "excluir" | "renomear"
    """
    if not host or not user or not password:
        raise ErroGravador("informe host, usuario e senha do gravador")
    if not canal:
        raise ErroGravador("informe o canal")
    base = _base(host, porta_gravador, connector_id)
    marca = detectar_marca(base, user, password)
    funcao = (_ACOES.get(marca) or {}).get(acao)
    if not funcao:
        raise ErroGravador(f"acao '{acao}' nao disponivel nesta marca")
    if acao in ("adicionar", "editar"):
        if not ip:
            raise ErroGravador("informe o IP da camera")
        if not cam_user or not cam_senha:
            raise ErroGravador("informe usuario e senha da camera")
    if acao == "renomear" and not nome:
        raise ErroGravador("informe o novo nome do canal")
    try:
        saida = funcao(base, user, password, canal=int(canal), ip=ip, cam_user=cam_user,
                       cam_senha=cam_senha, nome=nome, protocolo=protocolo, porta=porta,
                       porta_http=porta_http, porta_rtsp=porta_rtsp)
    except ErroGravador as exc:
        # Intelbras: em boa parte do parque (NVD 1408 fw 4.001, NVD 1516 fw
        # 4.000) a rota /cgi-bin/api/LogicDeviceManager/ NAO EXISTE e responde
        # "HTTP 400" ate para URL inventada -- o operador via "Bad Request" ao
        # soltar ou vincular canal. A mesma operacao sai pelo NetSDK, que mexe
        # so na entrada RemoteDevice do canal (ver intelbras_canal_sdk).
        # O NVD 1516 da SIERRA (10.200.0.211) responde "HTTP 501 Not Implemented"
        # para a mesma rota -- mesmo caso, outro codigo.
        if not (marca == "intelbras" and acao in ("adicionar", "editar", "excluir")
                and any(f"HTTP {c}" in str(exc) for c in (400, 404, 501))):
            raise
        saida = _intelbras_pelo_sdk(acao, host=host, user=user, password=password,
                                    canal=int(canal), connector_id=connector_id, ip=ip,
                                    cam_user=cam_user, cam_senha=cam_senha, nome=nome,
                                    protocolo=protocolo, porta=porta,
                                    porta_http=porta_http, porta_rtsp=porta_rtsp)
    saida.update({"ok": True, "acao": acao, "marca": marca, "canal": int(canal)})
    return saida


def _intelbras_pelo_sdk(acao: str, *, host: str, user: str, password: str, canal: int,
                        connector_id: str, ip: str, cam_user: str, cam_senha: str,
                        nome: str, protocolo: str, porta: Any, porta_http: Any,
                        porta_rtsp: Any) -> Dict[str, Any]:
    from app.services import intelbras_canal_sdk as sdk
    if acao == "excluir":
        r = sdk.soltar_canal(host, user, password, canal, connector_id=connector_id)
    else:
        r = sdk.gravar_canal(host, user, password, canal, ip, cam_user, cam_senha,
                             connector_id=connector_id, nome=nome, protocolo=protocolo,
                             porta_cam=porta, porta_http=porta_http, porta_rtsp=porta_rtsp)
    if not r.get("ok"):
        raise ErroGravador(r.get("error") or "o gravador recusou pelo NetSDK")
    return {"comando": "NetSDK RemoteDevice", "via": "sdk"}
