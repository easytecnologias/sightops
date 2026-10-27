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
import time
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
            # Hikvision responde 403 com ResponseStatus ("Invalid Operation")
            # para canal que nao existe -- e uma resposta, nao senha errada.
            # Tratado como senha, o PUT num canal vago abortava o "adicionar"
            # antes do POST que cria o canal, e so sobrescrever funcionava.
            if r.status_code == 403 and "<statusCode>" in (r.text or ""):
                return r.status_code, r.text
        except Exception as exc:
            raise ErroGravador(f"nao consegui falar com o gravador: {exc}") from exc
    raise ErroGravador("o gravador recusou usuario ou senha")


def _base(host: str, porta: Any, connector_id: str = "") -> str:
    # Escrita em gravador: com o conector errado ia pelo IP REAL, com a senha
    # do cliente, para o equipamento que respondesse ali.
    from app.services.recorder_xray import conferir_alcance
    try:
        conferir_alcance(host, connector_id)
    except ValueError as exc:
        raise ErroGravador(str(exc)) from exc
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
    # Firmware novo responde em isapi.org: lido com o namespace antigo, o
    # statusString vinha vazio e um erro de escrita passava como sucesso.
    from app.services.hik_xml import ler
    raiz = ler(corpo or "")
    if raiz is None:
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


# Porta de gerencia de cada protocolo no InputProxy. HIKVISION na 80 nao conecta:
# em 14/10/2026 o canal 9 do DS-7616NI da TELHA (InforBR) ficou ONVIF:80 e
# offline (chanDetectResult=accessFroDeviceParamFailure) enquanto o canal 10, a
# mesma linha de camera, funcionava em HIKVISION:8000.
_HIK_PORTA = {"HIKVISION": 8000, "ONVIF": 80}


def _hik_protocolos(protocolo: str) -> list:
    """Protocolos a tentar, na ordem. "" (Automatico) = os dois.

    A tela manda "Onvif"/"HIKVISION"/"Private"; Private e da Intelbras e o
    Hikvision nao conhece -- cai no automatico em vez de gravar lixo.
    """
    p = str(protocolo or "").strip().upper()
    return [p] if p in _HIK_PORTA else ["HIKVISION", "ONVIF"]


def _hik_canal_online(base: str, user: str, password: str, canal: int,
                      espera: float = 15.0) -> Tuple[Any, str]:
    """(True|False|None, motivo) segundo o PROPRIO gravador.

    O gravador aceita o PUT com qualquer protocolo -- o 200 so diz que a
    configuracao foi salva, nao que a camera conectou. Quem diz e o
    InputProxy/channels/status, alguns segundos depois. None = nao deu para ler.
    """
    fim = time.monotonic() + espera
    motivo = ""
    while True:
        try:
            cod, txt = _req("GET", f"{base}/ISAPI/ContentMgmt/InputProxy/channels/status",
                            user, password, timeout=10)
        except ErroGravador:
            return None, "nao consegui ler o status do canal"
        if not (cod and 200 <= cod < 300):
            return None, f"status do canal: HTTP {cod}"
        for bloco in re.findall(r"<InputProxyChannelStatus\b.*?</InputProxyChannelStatus>", txt, re.S):
            if not re.search(rf"<id>\s*{int(canal)}\s*</id>", bloco):
                continue
            if re.search(r"<online>\s*true\s*</online>", bloco, re.I):
                return True, ""
            m = re.search(r"<chanDetectResult>([^<]*)</chanDetectResult>", bloco)
            motivo = (m.group(1).strip() if m else "") or "offline"
        if time.monotonic() >= fim:
            return False, motivo or "canal nao apareceu no status"
        time.sleep(2.5)


def _hik_gravar(base, user, password, metodos, **k) -> Dict[str, Any]:
    """Grava o canal tentando os protocolos e confere se a camera conectou.

    Com protocolo escolhido, grava so ele. No Automatico, se o gravador aceitar
    mas a camera nao conectar, tenta o proximo; se nenhum conectar, fica o
    primeiro (HIKVISION, o que o parque mais usa) e a resposta diz que a
    camera nao conectou -- antes a tela dizia "Feito" e o canal ficava offline.
    """
    protocolos = _hik_protocolos(k.get("protocolo"))
    ultimo_erro = ""
    aceitos = []  # (protocolo, porta, metodo, url, corpo, motivo)
    for protocolo in protocolos:
        porta = k.get("porta") or _HIK_PORTA[protocolo]
        corpo = _hik_xml(k["canal"], k["ip"], k["cam_user"], k["cam_senha"],
                         k.get("nome") or "", protocolo, porta).encode("utf-8")
        for metodo, url in metodos:
            cod, txt = _req(metodo, url, user, password, corpo)
            if cod and 200 <= cod < 300 and not _hik_erro(txt):
                break
            ultimo_erro = _hik_erro(txt) or f"HTTP {cod}: {txt[:120]}"
        else:
            continue
        online, motivo = _hik_canal_online(base, user, password, k["canal"])
        comando = f"{metodo} InputProxy ({protocolo}:{porta})"
        if online is not False:
            return {"comando": comando, "resposta": txt[:200], "online": online,
                    **({"aviso": motivo} if motivo else {})}
        aceitos.append((protocolo, porta, metodo, url, corpo, motivo))
    if not aceitos:
        raise ErroGravador(f"o gravador nao aceitou a camera: {ultimo_erro}")
    protocolo, porta, metodo, url, corpo, motivo = aceitos[0]
    if len(aceitos) > 1:
        # Volta ao primeiro: o ultimo gravado foi o ONVIF.
        _req(metodo, url, user, password, corpo)
    tentados = ", ".join(f"{a[0]}:{a[1]}" for a in aceitos)
    return {"comando": f"{metodo} InputProxy ({protocolo}:{porta})", "online": False,
            "aviso": (f"o gravador salvou, mas a camera nao conectou ({motivo}; "
                      f"tentado {tentados}). Confira IP, usuario e senha da camera.")}


def _hik_add(base, user, password, **k) -> Dict[str, Any]:
    canal = int(k["canal"])
    return _hik_gravar(base, user, password,
                       (("PUT", f"{base}/ISAPI/ContentMgmt/InputProxy/channels/{canal}"),
                        ("POST", f"{base}/ISAPI/ContentMgmt/InputProxy/channels")), **k)


def _hik_editar(base, user, password, **k) -> Dict[str, Any]:
    canal = int(k["canal"])
    return _hik_gravar(base, user, password,
                       (("PUT", f"{base}/ISAPI/ContentMgmt/InputProxy/channels/{canal}"),), **k)


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


def _canal_ocupado(marca: str, base: str, user: str, password: str, canal: int) -> str:
    """IP (ou "uma camera") que ja esta no canal; "" se vago ou se nao deu
    para ler -- a tela ja so oferece canal livre; isto e a segunda trava."""
    try:
        if marca == "hikvision":
            cod, txt = _req("GET", f"{base}/ISAPI/ContentMgmt/InputProxy/channels/{int(canal)}",
                            user, password, timeout=10)
            if cod and 200 <= cod < 300:
                m = re.search(r"<(?:ipAddress|hostName)>\s*([^<\s]+)\s*<", txt or "")
                return m.group(1) if m else "uma camera"
            return ""  # 403 "Invalid Operation" = canal vago
        if marca == "intelbras":
            from app.services.recorder_xray import _endereco_de_canal
            cod, txt = _req("GET", f"{base}/cgi-bin/LogicDeviceManager.cgi?action=getCameraAll",
                            user, password, timeout=20)
            if not (cod and 200 <= cod < 300):
                return ""
            campos = dict(re.findall(rf"camera\[{int(canal) - 1}\]\.([^=\r\n]+)=([^\r\n]*)", txt or ""))
            if str(campos.get("Type", "")).strip().lower() == "compose":
                return ""
            return _endereco_de_canal(campos.get("DeviceInfo.Address")) or ""
    except ErroGravador:
        return ""
    return ""


def executar(acao: str, *, host: str, user: str, password: str, canal: int,
             porta_gravador: Any = None, connector_id: str = "",
             ip: str = "", cam_user: str = "", cam_senha: str = "", nome: str = "",
             protocolo: str = "", porta: Any = None, porta_http: Any = None,
             porta_rtsp: Any = None, url_principal: str = "", url_extra: str = "",
             camera_hik: bool = False) -> Dict[str, Any]:
    """Executa a acao no gravador e devolve o que foi feito.

    acao: "adicionar" | "editar" | "excluir" | "renomear"
    protocolo (adicionar/editar): "" = como sempre foi (sem conferir imagem);
    "adaptativo" | "private" | "onvif" | "general" (Personalizado, RTSP
    manual) -- esses conferem se o gravador ja entrega imagem do canal.
    """
    modo = _modo_protocolo(protocolo)
    if modo and acao in ("adicionar", "editar"):
        return _gravar_com_modo(acao, modo, host=host, user=user, password=password, canal=int(canal),
                                porta_gravador=porta_gravador, connector_id=connector_id, ip=ip,
                                cam_user=cam_user, cam_senha=cam_senha, nome=nome, porta=porta,
                                porta_http=porta_http, porta_rtsp=porta_rtsp,
                                url_principal=url_principal, url_extra=url_extra, camera_hik=camera_hik)
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
    if acao == "adicionar":
        # "Adicionar" nunca substitui: no Hikvision o PUT no canal troca a
        # camera que estiver la, sem perguntar. Quem troca e "Trocar camera".
        ocupado = _canal_ocupado(marca, base, user, password, int(canal))
        if ocupado:
            raise ErroGravador(f"o canal {int(canal)} ja tem a camera {ocupado} -- "
                               "nada foi gravado; para substituir use \"Trocar camera\"")
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
        saida = _intelbras_pelo_sdk(acao, base=base, host=host, user=user, password=password,
                                    canal=int(canal), connector_id=connector_id, ip=ip,
                                    cam_user=cam_user, cam_senha=cam_senha, nome=nome,
                                    protocolo=protocolo, porta=porta,
                                    porta_http=porta_http, porta_rtsp=porta_rtsp)
    saida.update({"ok": True, "acao": acao, "marca": marca, "canal": int(canal)})
    return saida


def _porta_sdk_intelbras(base: str, user: str, password: str) -> int:
    """Porta do NetSDK que o PROPRIO gravador informa (DVRIP.TCPPort).

    O SDK ia sempre na 37777. O NVD 7132 do PERUCABA (10.10.9.122, web na
    8088) tem a porta trocada: a 37777 recusa a conexao e excluir canal dava
    "o gravador nao respondeu na porta 37777" com o gravador no ar. Leitura so
    (getConfig); sem resposta, fica a padrao.
    """
    try:
        status, txt = _req("GET", f"{base}/cgi-bin/configManager.cgi?action=getConfig&name=DVRIP",
                           user, password, timeout=10)
        m = re.search(r"DVRIP\.TCPPort\s*=\s*(\d+)", txt or "") if status == 200 else None
        if m and 0 < int(m.group(1)) < 65536:
            return int(m.group(1))
    except Exception:
        pass
    return 37777


def _intelbras_pelo_sdk(acao: str, *, base: str, host: str, user: str, password: str, canal: int,
                        connector_id: str, ip: str, cam_user: str, cam_senha: str,
                        nome: str, protocolo: str, porta: Any, porta_http: Any,
                        porta_rtsp: Any, url_principal: str = "", url_extra: str = "") -> Dict[str, Any]:
    from app.services import intelbras_canal_sdk as sdk
    porta_sdk = _porta_sdk_intelbras(base, user, password)
    if acao == "excluir":
        r = sdk.soltar_canal(host, user, password, canal, connector_id=connector_id, porta=porta_sdk)
    else:
        r = sdk.gravar_canal(host, user, password, canal, ip, cam_user, cam_senha,
                             connector_id=connector_id, nome=nome, protocolo=protocolo,
                             porta=porta_sdk, porta_cam=porta, porta_http=porta_http,
                             porta_rtsp=porta_rtsp, url_principal=url_principal, url_extra=url_extra)
    if not r.get("ok"):
        raise ErroGravador(r.get("error") or "o gravador recusou pelo NetSDK")
    return {"comando": "NetSDK RemoteDevice", "via": "sdk"}


# ------------------------------------------------------------------ modos de protocolo
# O que o tecnico escolhe no app: Adaptativo (o SightOps tenta e confere),
# Intelbras (protocolo proprio), ONVIF ou Personalizado (RTSP manual).
# Em 26/10/2026 uma Hikvision foi posta no NVD 7132 (RESERVA 03) sem protocolo:
# o SightOps mandou "Private" e o PROPRIO gravador trocou para ONVIF -- deu
# certo por causa do firmware, nao por nos. Aqui a escolha e explicita.
_MODOS = {"adaptativo": "adaptativo", "auto": "adaptativo", "automatico": "adaptativo",
          "private": "private", "intelbras": "private", "privado": "private",
          "onvif": "onvif", "general": "general", "personalizado": "general", "custom": "general"}
_INTELBRAS_PROTO = {"private": "Private", "onvif": "Onvif", "general": "General"}
_HIK_PROTO = {"adaptativo": "", "private": "HIKVISION", "onvif": "ONVIF"}
_NOME_MODO = {"private": "Intelbras", "onvif": "ONVIF", "general": "Personalizado (RTSP)"}


def _modo_protocolo(protocolo: str) -> str:
    """"" para o fluxo antigo (protocolo vazio ou o valor cru das telas antigas:
    "Private", "Onvif", "HIKVISION"); senao o modo novo."""
    p = str(protocolo or "").strip().lower()
    if p in ("", "hikvision") or str(protocolo or "").strip() in ("Private", "Onvif"):
        return ""
    return _MODOS.get(p, "")


def _intelbras_imagem(base: str, user: str, password: str, canal: int,
                      tentativas: int = 3, intervalo: float = 4.0) -> Any:
    """O gravador ja entrega imagem do canal? True/False/None (nao deu para
    perguntar). A camera leva alguns segundos para conectar depois de gravada."""
    from app.services.nvr_status_service import _imagem_do_canal
    ultimo = None
    for i in range(tentativas):
        if i:
            time.sleep(intervalo)
        # 3 x 5 s + esperas: o Adaptativo inteiro (ate 3 gravacoes e 2
        # conferencias) cabe nos 100 s que o Cloudflare deixa a requisicao viver.
        r = _imagem_do_canal(base, HTTPDigestAuth(user, password), int(canal), 5.0)
        if r is True:
            return True
        ultimo = r if r is not None else ultimo
    return False if ultimo is not None else None


def _gravar_intelbras(acao: str, proto: str, *, base: str, host: str, user: str, password: str,
                      canal: int, connector_id: str, **k) -> Dict[str, Any]:
    """Grava o canal no Intelbras com o protocolo dado. Personalizado vai direto
    pelo NetSDK (a API JSON nao leva as URLs); os outros pela API e, se o
    gravador nao tiver a rota, pelo NetSDK (o mesmo fallback de `executar`)."""
    if proto == "General":
        return _intelbras_pelo_sdk(acao, base=base, host=host, user=user, password=password,
                                   canal=canal, connector_id=connector_id, protocolo=proto, **k)
    funcao = _ACOES["intelbras"][acao]
    sem_url = {c: v for c, v in k.items() if c not in ("url_principal", "url_extra")}
    try:
        return funcao(base, user, password, canal=canal, protocolo=proto, **sem_url)
    except ErroGravador as exc:
        if not any(f"HTTP {c}" in str(exc) for c in (400, 404, 501)):
            raise
        return _intelbras_pelo_sdk(acao, base=base, host=host, user=user, password=password,
                                   canal=canal, connector_id=connector_id, protocolo=proto, **k)


def _gravar_com_modo(acao: str, modo: str, *, host: str, user: str, password: str, canal: int,
                     porta_gravador: Any, connector_id: str, ip: str, cam_user: str, cam_senha: str,
                     nome: str, porta: Any, porta_http: Any, porta_rtsp: Any,
                     url_principal: str, url_extra: str, camera_hik: bool) -> Dict[str, Any]:
    if not host or not user or not password:
        raise ErroGravador("informe host, usuario e senha do gravador")
    if not ip:
        raise ErroGravador("informe o IP da camera")
    if not cam_user or not cam_senha:
        raise ErroGravador("informe usuario e senha da camera")
    if modo == "general" and not str(url_principal or "").strip().lower().startswith("rtsp://"):
        raise ErroGravador("Personalizado: informe o endereco RTSP principal (rtsp://...)")
    base = _base(host, porta_gravador, connector_id)
    marca = detectar_marca(base, user, password)
    if acao == "adicionar":
        ocupado = _canal_ocupado(marca, base, user, password, canal)
        if ocupado:
            raise ErroGravador(f"o canal {canal} ja tem a camera {ocupado} -- nada foi gravado; "
                               "para substituir use \"Trocar IP\"")
    comum = dict(ip=ip, cam_user=cam_user, cam_senha=cam_senha, nome=nome, porta=porta,
                 porta_http=porta_http, porta_rtsp=porta_rtsp)

    if marca == "hikvision":
        if modo == "general":
            raise ErroGravador("Personalizado (RTSP) por enquanto so em gravador Intelbras")
        funcao = _ACOES["hikvision"][acao]
        saida = funcao(base, user, password, canal=canal, protocolo=_HIK_PROTO[modo], **comum)
        saida.update({"ok": True, "acao": acao, "marca": marca, "canal": canal, "modo": modo})
        return saida
    if marca != "intelbras":
        raise ErroGravador(f"marca de gravador nao suportada: {marca}")

    # Adaptativo: Hikvision (pelo inventario) quase nunca fala o protocolo
    # Intelbras -- comeca pelo ONVIF. As outras, Intelbras primeiro.
    ordem = (["onvif", "private"] if camera_hik else ["private", "onvif"]) if modo == "adaptativo" else [modo]
    tentados = []
    acao_vez = acao
    for m in ordem:
        _gravar_intelbras(acao_vez, _INTELBRAS_PROTO[m], base=base, host=host, user=user, password=password,
                          canal=canal, connector_id=connector_id, url_principal=url_principal,
                          url_extra=url_extra, **comum)
        acao_vez = "editar"  # depois da primeira gravacao o canal ja e da camera
        imagem = _intelbras_imagem(base, user, password, canal)
        tentados.append(f"{_NOME_MODO[m]}: {'com imagem' if imagem else 'sem imagem' if imagem is False else 'nao deu para conferir'}")
        if imagem:
            return {"ok": True, "acao": acao, "marca": marca, "canal": canal, "modo": modo,
                    "protocolo_usado": _NOME_MODO[m], "online": True, "tentados": tentados,
                    "comando": f"canal {canal} em {_NOME_MODO[m]}"}
        if imagem is None:
            break  # nao da para conferir: nao fica trocando protocolo as cegas
    if len(ordem) > 1 and len(tentados) > 1:
        # Nenhum deu imagem: volta ao primeiro da ordem (o mais provavel).
        _gravar_intelbras("editar", _INTELBRAS_PROTO[ordem[0]], base=base, host=host, user=user,
                          password=password, canal=canal, connector_id=connector_id,
                          url_principal=url_principal, url_extra=url_extra, **comum)
    return {"ok": True, "acao": acao, "marca": marca, "canal": canal, "modo": modo,
            "protocolo_usado": _NOME_MODO[ordem[0]], "online": False, "tentados": tentados,
            "comando": f"canal {canal} em {_NOME_MODO[ordem[0]]}",
            "aviso": "o gravador aceitou, mas ainda nao mostra imagem (" + "; ".join(tentados)
                     + "). Confira usuario e senha da camera" + (" e o endereco RTSP" if modo == "general" else "")}
