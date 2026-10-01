"""Raio-X do gravador: tudo que o equipamento sabe responder, em um objeto so.

Por que existe: a tela de Implantacao > Gravadores mostrava modelo, serial e uma
grade de canais adivinhada. O equipamento responde muito mais -- no NVD 7132 de
Perucaba sao 80 secoes de configuracao, e foi ai que apareceu que o NTP estava
desligado (o relogio que carimba a gravacao andava sozinho) e que a perda de
video so estava ligada em 10 dos 32 canais: 22 cameras podiam cair sem gerar
evento nenhum.

Duas APIs completamente diferentes:
  Intelbras/Dahua  CGI       configManager.cgi?action=getConfig&name=<secao>
  Hikvision        ISAPI     /ISAPI/<recurso>, XML

RITMO: o `name=All` da Intelbras devolve 4,8 MB e demora. Aqui as secoes sao
pedidas uma a uma, em paralelo, e so as que a tela usa.
"""
from __future__ import annotations

import collections
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

import requests
import urllib3
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from app.services import connector_routing_vnat as _vnat

urllib3.disable_warnings()

NS = {"h": "http://www.hikvision.com/ver20/XMLSchema"}
_TEMPO = 12.0
# Pedir tudo de uma vez derruba o CGI de alguns modelos; 6 de cada vez passou
# em todos os que testei.
_PARALELO = 6

# Secoes da Intelbras que a tela usa. Nome -> rotulo em portugues.
_SECOES_CGI = {
    "Network": "rede",
    "NTP": "ntp",
    "Email": "email",
    "SNMP": "snmp",
    "Https": "https",
    "ChannelTitle": "titulos",
    "Encode": "encode",
    "RecordMode": "gravacao",
    "T2UServer": "plataforma",
    "MotionDetect": "movimento",
    "LossDetect": "perda_video",
    "BlindDetect": "encoberta",
    "MovedDetect": "movida",
    "AudioDetect": "audio",
    "StorageLowSpace": "al_disco_cheio",
    "StorageFailure": "al_disco_falhou",
    "StorageNotExist": "al_sem_disco",
    "IPConflict": "al_ip_duplicado",
    "MacConflict": "al_mac_duplicado",
    "NetAbort": "al_rede_caiu",
    "LoginFailureAlarm": "al_login_falho",
    "FanSpeedAlarm": "al_ventoinha",
    "NAS": "nas",
    "MonitorTour": "ronda",
}

_ROTAS_ISAPI = {
    "/ISAPI/System/deviceInfo": "equipamento",
    "/ISAPI/System/status": "status",
    "/ISAPI/System/time": "hora",
    "/ISAPI/System/Network/interfaces": "rede",
    "/ISAPI/ContentMgmt/Storage": "discos",
    "/ISAPI/ContentMgmt/InputProxy/channels": "canais",
    "/ISAPI/ContentMgmt/InputProxy/channels/status": "canais_status",
    "/ISAPI/ContentMgmt/InputProxy/channels/capabilities": "capacidade",
    "/ISAPI/Streaming/channels": "streams",
    "/ISAPI/Security/users": "usuarios",
    "/ISAPI/Event/triggers": "gatilhos",
}


def _pedir(url: str, user: str, password: str, timeout: float = _TEMPO) -> Tuple[int | None, str]:
    """Digest primeiro, Basic depois: gravador antigo so fala Basic."""
    for auth in (HTTPDigestAuth(user, password), HTTPBasicAuth(user, password)):
        try:
            r = requests.get(url, auth=auth, timeout=timeout, verify=False)
            if r.status_code not in (401, 403):
                return r.status_code, (r.text or "")
        except Exception as exc:  # timeout, conexao recusada, DNS
            return None, str(exc)
    return 401, ""


def _base(host: str, porta: Any, connector_id: str = "") -> str:
    """Conector isolado so responde no IP virtual -- quem traduz e o vnat."""
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


def detectar_marca(base: str, user: str, password: str) -> str:
    """"hikvision" ou "intelbras", perguntando ao equipamento.

    401/403 no ISAPI tambem conta como Hikvision: a rota existe e so pediu
    credencial. Num Intelbras ela nem existiria (404) -- sem isso, senha errada
    fazia o Hikvision ser tratado como Intelbras e tudo falhava em silencio.
    """
    cod, corpo = _pedir(f"{base}/ISAPI/System/deviceInfo", user, password, timeout=6.0)
    if cod and 200 <= cod < 300 and "deviceinfo" in (corpo or "").lower():
        return "hikvision"
    if cod in (401, 403):
        return "hikvision"
    return "intelbras"


# --------------------------------------------------------------- Intelbras
def _cgi_pares(texto: str) -> Dict[str, str]:
    saida: Dict[str, str] = {}
    for linha in (texto or "").splitlines():
        if "=" in linha:
            chave, _, valor = linha.partition("=")
            saida[chave.strip()] = valor.strip()
    return saida


def _cgi_indexado(pares: Dict[str, str], prefixo: str, campo: str) -> Dict[int, str]:
    """De `table.LossDetect[7].Enable=true` tira {7: "true"}."""
    padrao = re.compile(r"^table\." + re.escape(prefixo) + r"\[(\d+)\]\." + re.escape(campo) + r"$")
    saida: Dict[int, str] = {}
    for chave, valor in pares.items():
        m = padrao.match(chave)
        if m:
            saida[int(m.group(1))] = valor
    return saida


def _xray_intelbras(base: str, user: str, password: str) -> Dict[str, Any]:
    cru: Dict[str, Dict[str, str]] = {}

    def buscar(nome: str) -> Tuple[str, Dict[str, str]]:
        cod, corpo = _pedir(
            f"{base}/cgi-bin/configManager.cgi?action=getConfig&name={nome}", user, password
        )
        return nome, (_cgi_pares(corpo) if cod and 200 <= cod < 300 else {})

    with ThreadPoolExecutor(max_workers=_PARALELO) as pool:
        for nome, pares in pool.map(buscar, list(_SECOES_CGI)):
            cru[nome] = pares

    def v(secao: str, chave: str) -> str:
        return cru.get(secao, {}).get(f"table.{chave}", "")

    # identidade vem do magicBox, nao do configManager
    equipamento: Dict[str, str] = {}
    for caminho in (
        "/cgi-bin/magicBox.cgi?action=getDeviceType",
        "/cgi-bin/magicBox.cgi?action=getSystemInfo",
        "/cgi-bin/magicBox.cgi?action=getSoftwareVersion",
        "/cgi-bin/magicBox.cgi?action=getMachineName",
    ):
        cod, corpo = _pedir(f"{base}{caminho}", user, password, timeout=6.0)
        if cod and 200 <= cod < 300:
            for chave, valor in _cgi_pares(corpo).items():
                equipamento[chave.lower()] = valor

    # cameras e canais
    cod, corpo = _pedir(
        f"{base}/cgi-bin/LogicDeviceManager.cgi?action=getCameraAll", user, password, timeout=20.0
    )
    cams: Dict[int, Dict[str, str]] = {}
    if cod and 200 <= cod < 300:
        for idx, chave, valor in re.findall(r"camera\[(\d+)\]\.([^=\r\n]+)=([^\r\n]*)", corpo):
            cams.setdefault(int(idx), {})[chave.strip()] = valor.strip()

    titulos = _cgi_indexado(cru.get("ChannelTitle", {}), "ChannelTitle", "Name")
    deteccoes = {
        rotulo: _cgi_indexado(cru.get(secao, {}), secao, "Enable")
        for secao, rotulo in (
            ("MotionDetect", "movimento"), ("LossDetect", "perda_video"),
            ("BlindDetect", "encoberta"), ("MovedDetect", "movida"), ("AudioDetect", "audio"),
        )
    }

    # O getCameraAll do NVD 7132 devolve uma entrada A MAIS no fim da lista
    # (indice 32 num gravador de 32 canais): `Type=Compose`, que e o canal
    # VIRTUAL de mosaico do proprio gravador, nao uma camera. Ela virava um
    # "canal 33" que nao existe em equipamento nenhum -- e aparecia como canal
    # livre, oferecendo encaixar camera onde nao da.
    com_dado = {
        i for i, c in cams.items()
        if str(c.get("Type", "")).strip().lower() != "compose"
        and (str(c.get("DeviceInfo.Address", "")).strip()
             or any(str(v).strip() for k, v in c.items() if k.startswith("DeviceInfo.")))
    }
    canais: List[Dict[str, Any]] = []
    for i in sorted(set(titulos) | com_dado):
        cam = cams.get(i, {})
        enc = cru.get("Encode", {})
        largura = enc.get(f"table.Encode[{i}].MainFormat[0].Video.Width", "")
        altura = enc.get(f"table.Encode[{i}].MainFormat[0].Video.Height", "")
        canais.append({
            "canal": i + 1,
            "nome": titulos.get(i, ""),
            "ip": cam.get("DeviceInfo.Address", ""),
            "modelo": cam.get("DeviceInfo.DeviceType", ""),
            "serial": cam.get("DeviceInfo.SerialNo", ""),
            "porta": cam.get("DeviceInfo.Port", ""),
            "porta_http": cam.get("DeviceInfo.HttpPort", ""),
            "poe": cam.get("DeviceInfo.PoEPort", ""),
            "protocolo": cam.get("DeviceInfo.ProtocolType", ""),
            "ativo": cam.get("DeviceInfo.Enable", "") == "true",
            "resolucao": f"{largura}x{altura}" if largura and altura else "",
            "fps": enc.get(f"table.Encode[{i}].MainFormat[0].Video.FPS", ""),
            "taxa_kbps": enc.get(f"table.Encode[{i}].MainFormat[0].Video.BitRate", ""),
            "codec": enc.get(f"table.Encode[{i}].MainFormat[0].Video.Compression", ""),
            "perfil": enc.get(f"table.Encode[{i}].MainFormat[0].Video.Profile", ""),
            "movimento": deteccoes["movimento"].get(i) == "true",
            "perda_video": deteccoes["perda_video"].get(i) == "true",
            "encoberta": deteccoes["encoberta"].get(i) == "true",
            "movida": deteccoes["movida"].get(i) == "true",
        })

    # discos
    cod, corpo = _pedir(
        f"{base}/cgi-bin/storageDevice.cgi?action=getDeviceAllInfo", user, password, timeout=20.0
    )
    discos: List[Dict[str, Any]] = []
    if cod and 200 <= cod < 300:
        # Um DISCO e um `list.info[N]`; cada `Detail[i]` dele e uma PARTICAO.
        # O NVD 7132 de Perucaba tem 3 discos de 6 TB particionados em 4 cada
        # -- contar Detail dava "12 discos", que nao existem. Agora soma as
        # particoes dentro de cada disco e conta disco.
        partes: Dict[int, Dict[int, Dict[str, str]]] = {}
        for grupo, idx, chave, valor in re.findall(
                r"list\.info\[(\d+)\]\.Detail\[(\d+)\]\.(\w+)=([^\r\n]*)", corpo):
            partes.setdefault(int(grupo), {}).setdefault(int(idx), {})[chave] = valor.strip()
        # Nome e estado ficam no nivel do disco, fora de Detail.
        cabecas: Dict[int, Dict[str, str]] = {}
        for grupo, chave, valor in re.findall(
                r"list\.info\[(\d+)\]\.(Name|State|HealthDataFlag)=([^\r\n]*)", corpo):
            cabecas.setdefault(int(grupo), {})[chave] = valor.strip()

        for ordem, grupo in enumerate(sorted(partes), start=1):
            fatias = partes[grupo]
            total = usado = 0.0
            com_erro = False
            for d in fatias.values():
                try:
                    total += float(d.get("TotalBytes") or 0)
                    usado += float(d.get("UsedBytes") or 0)
                except Exception:
                    pass
                if (d.get("IsError") or "").lower() == "true":
                    com_erro = True
            cab = cabecas.get(grupo, {})
            estado = (cab.get("State") or "").strip()
            if estado and estado.lower() not in ("success", "ok", "normal"):
                com_erro = True
            discos.append({
                "id": ordem,
                "total_tb": round(total / 1e12, 2) if total else 0,
                "usado_tb": round(usado / 1e12, 2) if usado else 0,
                "erro": com_erro,
                "tipo": (list(fatias.values())[0].get("Type", "") if fatias else ""),
                "caminho": cab.get("Name") or (list(fatias.values())[0].get("Path", "")[:-1] if fatias else ""),
                "particoes": len(fatias),
                "estado": estado,
            })

    def contar(rotulo: str) -> Dict[str, int]:
        mapa = deteccoes.get(rotulo, {})
        return {"ligados": sum(1 for x in mapa.values() if x == "true"), "total": len(mapa)}

    return {
        "marca": "Intelbras",
        "equipamento": {
            "modelo": equipamento.get("type", ""),
            "serial": equipamento.get("serialnumber", ""),
            "firmware": equipamento.get("version", ""),
            "compilacao": equipamento.get("build", ""),
            "processador": equipamento.get("processor", ""),
            "plataforma": equipamento.get("updateserial", ""),
            "nome": equipamento.get("name", ""),
        },
        "rede": {
            "ip": v("Network", "Network.eth0.IPAddress"),
            "mascara": v("Network", "Network.eth0.SubnetMask"),
            "gateway": v("Network", "Network.eth0.DefaultGateway"),
            "mac": v("Network", "Network.eth0.PhysicalAddress"),
            "mtu": v("Network", "Network.eth0.MTU"),
            "dns": v("Network", "Network.DNSServer[0]"),
        },
        "servicos": {
            "ntp_ligado": v("NTP", "NTP.Enable") == "true",
            "ntp_servidor": v("NTP", "NTP.Address"),
            "email_ligado": v("Email", "Email.Enable") == "true",
            "snmp_ligado": v("SNMP", "SNMP.Enable") == "true",
            "https_ligado": v("Https", "Https.Enable") == "true",
            "nas_ligado": v("NAS", "NAS[0].Enable") == "true",
        },
        # Modo de gravacao por canal. RecordMode[N].Mode: 0 = programado,
        # 1 = manual (grava sempre), 2 = desligado. Sem isso o relatorio
        # mostrava a gravacao de todo canal como "n/c".
        "gravacao": {
            "por_canal": {
                int(n) + 1: ("desligado" if modo == "2" else
                             "manual" if modo == "1" else "programado")
                for n, modo in sorted(
                    _cgi_indexado(cru.get("RecordMode", {}), "RecordMode", "Mode").items()
                )
            },
        },
        # Nuvem do fabricante. No Intelbras e o T2UServer (intelbrasp2p.com.br);
        # le-se apenas se esta ligado e para qual servidor -- a chave e a senha
        # de verificacao que vem na mesma resposta NAO sao lidas nem guardadas.
        "plataforma": {
            "ligada": v("T2UServer", "T2UServer[0].Enable") == "true",
            "servidor": v("T2UServer", "T2UServer[0].Address"),
        },
        "deteccao": {rotulo: contar(rotulo) for rotulo in deteccoes},
        "alarmes": {
            rotulo: (cru.get(secao, {}).get(f"table.{secao}.Enable")
                     or cru.get(secao, {}).get(f"table.{secao}[0].Enable")) == "true"
            for secao, rotulo in (
                ("StorageLowSpace", "disco_cheio"), ("StorageFailure", "disco_falhou"),
                ("StorageNotExist", "sem_disco"), ("IPConflict", "ip_duplicado"),
                ("MacConflict", "mac_duplicado"), ("NetAbort", "rede_caiu"),
                ("LoginFailureAlarm", "login_falho"), ("FanSpeedAlarm", "ventoinha"),
            )
        },
        "canais": canais,
        "discos": discos,
        "total_canais": len(titulos) or len(canais),
    }


# --------------------------------------------------------------- Hikvision
def _txt(no, caminho: str) -> str:
    if no is None:
        return ""
    return (no.findtext(caminho, "", NS) or "").strip()


def _xray_hikvision(base: str, user: str, password: str) -> Dict[str, Any]:
    cru: Dict[str, str] = {}

    def buscar(rota: str) -> Tuple[str, str]:
        cod, corpo = _pedir(f"{base}{rota}", user, password, timeout=30.0)
        return rota, (corpo if cod and 200 <= cod < 300 else "")

    with ThreadPoolExecutor(max_workers=_PARALELO) as pool:
        for rota, corpo in pool.map(buscar, list(_ROTAS_ISAPI)):
            cru[_ROTAS_ISAPI[rota]] = corpo

    def arvore(chave: str):
        try:
            return ET.fromstring(cru.get(chave) or "")
        except Exception:
            return None

    eq = arvore("equipamento")
    equipamento = {
        "modelo": _txt(eq, "h:model"),
        "serial": _txt(eq, "h:serialNumber"),
        "firmware": _txt(eq, "h:firmwareVersion"),
        "compilacao": _txt(eq, "h:firmwareReleasedDate"),
        "nome": _txt(eq, "h:deviceName"),
        "tipo": _txt(eq, "h:deviceType"),
        "mac": _txt(eq, "h:macAddress"),
    }

    st = arvore("status")
    uptime = _txt(st, "h:deviceUpTime")
    rd = arvore("rede")
    rede = {
        "ip": _txt(rd, ".//h:ipAddress"),
        "mascara": _txt(rd, ".//h:subnetMask"),
        "gateway": _txt(rd, ".//h:DefaultGateway/h:ipAddress"),
        "mac": _txt(rd, ".//h:MACAddress"),
        "mtu": _txt(rd, ".//h:MTU"),
        "enderecamento": _txt(rd, ".//h:addressingType"),
    }

    # canais: junta a lista com o status
    nomes: Dict[int, Dict[str, str]] = {}
    lista = arvore("canais")
    if lista is not None:
        for e in lista.findall(".//h:InputProxyChannel", NS):
            try:
                i = int(_txt(e, "h:id") or 0)
            except Exception:
                continue
            d = e.find("h:sourceInputPortDescriptor", NS)
            nomes[i] = {
                "nome": _txt(e, "h:name"),
                "ip": _txt(d, "h:ipAddress"),
                "protocolo": _txt(d, "h:proxyProtocol"),
                "porta": _txt(d, "h:managePortNo"),
                "usuario": _txt(d, "h:userName"),
            }
    estados: Dict[int, bool] = {}
    stt = arvore("canais_status")
    if stt is not None:
        for e in stt.findall(".//h:InputProxyChannelStatus", NS):
            try:
                i = int(_txt(e, "h:id") or 0)
            except Exception:
                continue
            estados[i] = _txt(e, "h:online") == "true"

    # resolucao/codec por canal vem do Streaming
    streams: Dict[int, Dict[str, str]] = {}
    for bloco in re.findall(r"<StreamingChannel\b.*?</StreamingChannel>", cru.get("streams") or "", re.S):
        m = re.search(r"<id>(\d+)</id>", bloco)
        if not m:
            continue
        canal = int(m.group(1)) // 100  # 101 = canal 1 stream principal
        if int(m.group(1)) % 100 != 1:
            continue
        def campo(nome: str) -> str:
            mm = re.search(rf"<{nome}>([^<]*)</{nome}>", bloco)
            return (mm.group(1).strip() if mm else "")
        streams[canal] = {
            "codec": campo("videoCodecType"),
            "largura": campo("videoResolutionWidth"),
            "altura": campo("videoResolutionHeight"),
            "fps": campo("maxFrameRate"),
            "taxa": campo("vbrUpperCap") or campo("constantBitRate"),
        }

    canais: List[Dict[str, Any]] = []
    for i in sorted(set(nomes) | set(estados)):
        base_c = nomes.get(i, {})
        s = streams.get(i, {})
        fps = s.get("fps", "")
        try:  # ISAPI devolve fps x100
            fps = str(int(int(fps) / 100)) if fps else ""
        except Exception:
            pass
        canais.append({
            "canal": i,
            "nome": base_c.get("nome", "") or f"Canal {i:02d}",
            "ip": base_c.get("ip", ""),
            "modelo": "",
            "serial": "",
            "porta": base_c.get("porta", ""),
            "protocolo": base_c.get("protocolo", ""),
            "ativo": estados.get(i, False),
            "online": estados.get(i, False),
            "resolucao": (f"{s.get('largura')}x{s.get('altura')}"
                          if s.get("largura") and s.get("altura") else ""),
            "fps": fps,
            "taxa_kbps": s.get("taxa", ""),
            "codec": s.get("codec", ""),
        })

    discos: List[Dict[str, Any]] = []
    dsk = arvore("discos")
    if dsk is not None:
        for d in dsk.findall(".//h:hdd", NS):
            try:
                cap = int(_txt(d, "h:capacity") or 0)
                livre = int(_txt(d, "h:freeSpace") or 0)
            except Exception:
                cap = livre = 0
            discos.append({
                "id": _txt(d, "h:id"),
                "nome": _txt(d, "h:hddName"),
                "tipo": _txt(d, "h:hddType"),
                "situacao": _txt(d, "h:status"),
                "total_tb": round(cap / 1e6, 2) if cap else 0,   # vem em MB
                "livre_tb": round(livre / 1e6, 2) if livre else 0,
                "erro": _txt(d, "h:status").lower() not in ("ok", ""),
            })

    # capacidade real de canais, em vez de chutar 32
    total = 0
    m = re.search(r'<id\s+min="\d+"\s+max="(\d+)"', cru.get("capacidade") or "")
    if m:
        total = int(m.group(1))

    gatilhos = collections.Counter(re.findall(r"<eventType>([^<]+)</eventType>", cru.get("gatilhos") or ""))
    return {
        "marca": "Hikvision",
        "equipamento": equipamento,
        "uptime_s": uptime,
        "rede": rede,
        "servicos": {},
        "deteccao": {k: {"ligados": n, "total": len(canais)} for k, n in gatilhos.most_common(10)},
        "alarmes": {},
        "canais": canais,
        "discos": discos,
        "usuarios": len(re.findall(r"<User\b", cru.get("usuarios") or "")),
        "total_canais": total or len(canais),
    }


# Como o equipamento classifica o que encontra na rede, confirmado na varredura
# real do iNVD 5132 de BARRA: IPC (camera fixa), SD (speed dome), ITC (camera de
# placa/LPR), NVR (gravador), KEYBOARD (teclado de operacao).
#
# Separar por aqui e o que permite "buscar gravador" e "buscar camera" lerem a
# MESMA varredura e cada tela mostrar so o que interessa.
CLASSES_CAMERA = ("IPC", "SD", "ITC")
CLASSES_GRAVADOR = ("NVR", "DVR", "HCVR", "XVR", "MHDX", "HDCVI")


def _descobrir_dahua(base: str, user: str, password: str, rodadas: int = 3,
                     pausa: float = 1.2) -> Dict[str, Dict[str, str]]:
    """Varredura da rede pelo gravador, lida mais de uma vez e somada.

    `deviceDiscovery.cgi?action=attach` NAO devolve a rede inteira: devolve o
    que o equipamento ja coletou ate aquele instante, e a lista cresce enquanto
    os vizinhos respondem. Medido no iNVD 5132 de BARRA: a primeira leitura
    trouxe 243 dispositivos e 12 gravadores; a segunda, 276 e 14. Quem lesse uma
    vez so via um gravador existir e, segundos depois, sumir -- foi exatamente o
    que aconteceu com o 100.65.10.52 e o .54.

    Tres leituras curtas somadas, com chave pelo IP: o equipamento que apareceu
    em qualquer uma delas entra na lista.
    """
    import time as _t

    achados: Dict[str, Dict[str, str]] = {}
    erro = ""
    for volta in range(max(1, int(rodadas))):
        if volta:
            _t.sleep(pausa)
        cod, corpo = _pedir(
            f"{base}/cgi-bin/deviceDiscovery.cgi?action=attach&Types[0]=onvif&Types[1]=privateDahua",
            user, password, 30.0,
        )
        if not cod or not (200 <= cod < 300):
            erro = f"HTTP {cod}"
            continue
        bruto: Dict[int, Dict[str, str]] = {}
        for idx, chave, valor in re.findall(
                r"deviceInfo\[(\d+)\]\.([\w\.]+)=([^\r\n]*)", corpo or ""):
            bruto.setdefault(int(idx), {})[chave] = valor.strip()
        for item in bruto.values():
            ip = item.get("IPv4Address.IPAddress", "")
            if not ip or ip == "0.0.0.0":
                continue
            # Leitura mais nova vence: so completa o que faltava, nunca apaga.
            atual = achados.setdefault(ip, {})
            for k, v in item.items():
                if v:
                    atual[k] = v
    if not achados and erro:
        raise ValueError(f"o gravador nao respondeu a busca ({erro})")
    return achados


def buscar_gravadores(host: str, user: str, password: str, porta: Any = None,
                      connector_id: str = "") -> Dict[str, Any]:
    """Gravadores que ESTE gravador enxerga na rede dele.

    Para cadastrar um gravador novo e preciso saber o IP dele, e descobrir isso
    na mao significa varrer a rede do cliente por fora -- coisa que daqui nem da
    para fazer. Mas um gravador ja cadastrado esta na mesma LAN e enxerga os
    vizinhos: na BARRA, um iNVD 5132 achou outros 10 gravadores com IP, modelo e
    fabricante.

    E a mesma varredura de `buscar_cameras`, filtrada por classe de equipamento.
    So leitura.
    """
    base = _base(host, porta, connector_id)
    marca = detectar_marca(base, user, password)
    if marca == "hikvision":
        # O ISAPI so lista o que pode virar canal (camera). Gravador vizinho nao
        # aparece la -- por isso o Hikvision nao oferece esta busca.
        return {"marca": marca, "gravadores": [], "total": 0,
                "aviso": "o Hikvision nao lista gravadores vizinhos; use um gravador Intelbras para varrer"}

    bruto = _descobrir_dahua(base, user, password)

    achados: List[Dict[str, Any]] = []
    for item in bruto.values():
        ip = item.get("IPv4Address.IPAddress", "")
        classe = (item.get("DeviceClass") or "").upper()
        if not ip or ip == "0.0.0.0" or classe not in CLASSES_GRAVADOR:
            continue
        achados.append({
            "ip": ip,
            "mac": item.get("Mac", ""),
            "modelo": item.get("DeviceType", ""),
            "fabricante": item.get("Vendor") or item.get("Manufacturer", ""),
            "serial": item.get("SerialNo") or item.get("MachineName", ""),
            "porta": item.get("Port", "37777"),
            "porta_http": item.get("HttpPort", "80"),
            "firmware": item.get("Version", ""),
            "classe": classe,
            "canais": item.get("RemoteVideoInputChannels") or item.get("VideoInputChannels", ""),
            "ele_mesmo": ip == str(host),
        })
    achados.sort(key=lambda c: tuple(int(x) if x.isdigit() else 0 for x in c["ip"].split(".")))
    return {"marca": marca, "gravadores": achados, "total": len(achados)}


def buscar_cameras(host: str, user: str, password: str, porta: Any = None,
                   connector_id: str = "") -> Dict[str, Any]:
    """Pergunta ao GRAVADOR quais cameras ele enxerga na rede dele.

    Quem varre e o proprio equipamento, que esta na mesma rede das cameras --
    nos nao alcancamos a LAN do cliente para fazer isso daqui. No NVD 7132 de
    Perucaba essa chamada devolveu 317 dispositivos com IP, MAC, modelo e
    serial.

    So leitura. Devolve tambem quais ja estao em algum canal, para a tela nao
    oferecer uma camera que ja esta no gravador.
    """
    base = _base(host, porta, connector_id)
    marca = detectar_marca(base, user, password)

    if marca == "hikvision":
        # A busca do ISAPI e GET (o POST com SearchDescription devolve 401) e o
        # resultado vem em <VideoSourceDescriptor>, nao em <SearchResult>.
        # Confirmado no DS-7632NXI de Perucaba: 90 cameras.
        #
        # ATENCAO: cada bloco traz <userName> e <password> da camera em texto
        # puro -- o equipamento devolve isso sozinho. Nada disso e lido aqui,
        # para nao acabar no navegador nem em log.
        cod, corpo = _pedir(f"{base}/ISAPI/ContentMgmt/InputProxy/search", user, password, 30.0)
        if not cod or not (200 <= cod < 300):
            raise ValueError("o gravador nao respondeu a busca de cameras")
        achadas: List[Dict[str, Any]] = []
        ja_hik: List[str] = []
        for bloco in re.findall(r"<VideoSourceDescriptor>(.*?)</VideoSourceDescriptor>", corpo or "", re.S):
            def campo(nome: str, _b: str = "") -> str:
                m = re.search(rf"<{nome}>([^<]*)</{nome}>", bloco)
                return (m.group(1).strip() if m else "")
            ip = campo("ipAddress")
            if not ip or ip == "0.0.0.0":
                continue
            # O valor real deste modelo e "notAdded" (nao "no"): tratar o
            # desconhecido como "ja adicionada" escondia TODAS as cameras do
            # filtro "so as que faltam". So conta como adicionada quando diz.
            no_gravador = campo("addStatus").strip().lower() in ("added", "yes", "true", "success")
            if no_gravador:
                ja_hik.append(ip.lower())
            achadas.append({
                "ip": ip,
                "mac": campo("macAddress"),
                "modelo": campo("deviceModel"),
                "fabricante": "Hikvision" if campo("proxyProtocol").upper() == "HIKVISION" else (campo("proxyProtocol") or "ONVIF"),
                "serial": campo("serialNumber"),
                "porta": campo("managePortNo") or "8000",
                "porta_http": "80",
                "firmware": campo("firmwareVersion"),
                "inicializada": campo("activated").lower() != "false",
                "no_gravador": no_gravador,
            })
        achadas.sort(key=lambda c: tuple(int(x) if x.isdigit() else 0 for x in c["ip"].split(".")))
        return {"marca": marca, "cameras": achadas, "total": len(achadas),
                "ja_no_gravador": sorted(set(ja_hik))}

    # Intelbras/Dahua: varredura lida mais de uma vez e somada -- ver
    # _descobrir_dahua; uma leitura so perde equipamento que ainda nao
    # respondeu.
    bruto = _descobrir_dahua(base, user, password)

    # Quem ja esta em um canal, para nao oferecer de novo.
    cod2, corpo2 = _pedir(
        f"{base}/cgi-bin/configManager.cgi?action=getConfig&name=RemoteDevice", user, password, 25.0)
    ja = {ip.strip().lower() for ip in re.findall(r"\.Address=([^\r\n]+)", corpo2 or "")}

    cameras: List[Dict[str, Any]] = []
    for item in bruto.values():
        ip = item.get("IPv4Address.IPAddress", "")
        # 0.0.0.0 e o proprio anuncio de servicos do gravador, nao camera.
        if not ip or ip == "0.0.0.0":
            continue
        classe = (item.get("DeviceClass") or "").upper()
        if classe and classe not in CLASSES_CAMERA:
            continue
        cameras.append({
            "ip": ip,
            "mac": item.get("Mac", ""),
            "modelo": item.get("DeviceType", ""),
            "fabricante": item.get("Vendor") or item.get("Manufacturer", ""),
            "serial": item.get("SerialNo") or item.get("MachineName", ""),
            "porta": item.get("Port", "37777"),
            "porta_http": item.get("HttpPort", "80"),
            "firmware": item.get("Version", ""),
            # Init vazio/0 = camera de fabrica, ainda sem senha definida.
            "inicializada": bool((item.get("Init") or "").strip() not in ("", "0")),
            "no_gravador": ip.lower() in ja,
        })
    cameras.sort(key=lambda c: tuple(int(x) if x.isdigit() else 0 for x in c["ip"].split(".")))
    return {"marca": marca, "cameras": cameras, "total": len(cameras),
            "ja_no_gravador": sorted(ja)}


def raio_x(host: str, user: str, password: str, porta: Any = None,
           connector_id: str = "") -> Dict[str, Any]:
    """Le tudo que o gravador expoe. Levanta ValueError se nao entrar."""
    base = _base(host, porta, connector_id)
    marca = detectar_marca(base, user, password)
    dados = (_xray_hikvision if marca == "hikvision" else _xray_intelbras)(base, user, password)
    if not dados.get("equipamento", {}).get("modelo") and not dados.get("canais"):
        raise ValueError("o gravador respondeu, mas nao devolveu nada util -- confira usuario e senha")
    dados["host"] = host
    canais = dados.get("canais") or []
    total = int(dados.get("total_canais") or 0) or len(canais)
    # Canal sem IP esta LIVRE. O getCameraAll devolve a posicao mesmo vazia, e
    # conta-la como usada fazia o NVD 7132 mostrar 33 de 32 e zero livre.
    usados = sum(1 for c in canais if str(c.get("ip") or "").strip())
    dados["resumo"] = {
        "canais_total": total,
        "canais_usados": usados,
        "canais_livres": max(0, total - usados),
        "offline": sum(1 for c in canais if c.get("online") is False),
        "discos": len(dados.get("discos") or []),
        "discos_com_erro": sum(1 for d in dados.get("discos") or [] if d.get("erro")),
    }
    return dados
