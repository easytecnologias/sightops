"""Raio-X de CAMERA, no mesmo molde do raio-X de gravador.

Por que existe
--------------
O botao "Entrar na camera" do assistente CFTV chamava `/api/rescan-single-ip`,
que dispara `tools/inventory_dry.py` como subprocesso. Esse arquivo **nao
existe** -- nem no repositorio, nem na imagem em producao. Entao a chamada
devolvia HTTP 500 em 100% das vezes, e a tela traduzia isso para "Falha ao
conectar na camera. Confira IP/usuario/senha." O tecnico passava a culpar a
senha de uma camera que estava perfeitamente acessivel.

E, mesmo que o script existisse, nao funcionaria: `RescanSingleIPRequest` nao
tem campo `connector_id`, entao o IP ia cru para o scanner. Os doze conectores
do parque sao isolados (vnat) e so respondem no IP virtual -- o IP real da
camera nao tem rota a partir do container.

O raio-X de gravador ja resolvia os dois problemas, e resolveu bem. Este
modulo reaproveita as primitivas dele em vez de reescreve-las:

- `_base`           traduz IP real -> IP virtual do conector (vnat).
- `_pedir`          tenta Digest e depois Basic (equipamento antigo so fala Basic).
- `detectar_marca`  pergunta ao equipamento em vez de adivinhar pelo modelo.
- `_cgi_pares`      quebra a resposta `chave=valor` do CGI Dahua/Intelbras.

O formato de saida tambem imita o do gravador (`equipamento`, `rede`,
`achados`), para que a tela trate os dois do mesmo jeito.

Validado em equipamento real (05/10/2026), as duas marcas, sempre com o IP
REAL na entrada e a traducao vnat por conta do `_base`:

    Hikvision  10.50.11.1  (TELHA, conector isolado)
               IPC-B121H-C, firmware V5.8.10, mascara 255.255.254.0
               gravar_titulo -> statusCode 1 OK

    Intelbras  10.10.9.20  (Easy Tecnologias, via conector PERUCABA)
               VIP-1130-B-G2, serial LR7J430462731
               firmware 2.800.00IB006.0.T, mascara 255.255.252.0
               gravar_titulo -> HTTP 200 "OK"

Nos dois casos o titulo foi regravado com o MESMO valor de proposito: prova o
caminho de escrita sem alterar camera de cliente.

A mascara da Intelbras ali e 255.255.252.0, um /22. E a razao de `aplicar_ip`
LER a mascara da camera em vez de assumir /24: o chute teria tirado essa
camera da rede, e camera sem rota nao se conserta remotamente.

Por que nao o NetSDK
--------------------
A pergunta foi levantada e vale deixar respondida. As libs existem no
container (`/opt/netsdk/lib`, `/opt/hiksdk/lib`), mas neste projeto o SDK so
e usado para ATIVACAO de fabrica -- `CLIENT_SearchDevicesByIPs` e
`CLIENT_InitDevAccountByIP`, mais o equivalente Hikvision. Nao ha login nem
leitura de configuracao por SDK.

Nao foi preciso escrever: o HTTP cobriu tudo que o assistente precisa, nas
duas marcas, com as medicoes acima. E o SDK cobra caro por isso -- chamado
dentro do processo da API ele DERRUBA o processo (exit 139, core dumped,
reproduzido em 05/10/2026 logo apos `available()` retornar ok). Por isso
`intelbras_netsdk.py` ja o executa em subprocesso isolado. Trocar requisicao
HTTP por biblioteca C que segfalha, para obter o mesmo dado, seria piorar.

O SDK continua sendo o caminho certo para o que o HTTP realmente nao faz:
ativar camera de fabrica. Se um firmware Intelbras aparecer sem os CGI usados
aqui, o fallback por SDK (em subprocesso) e a saida -- nao antes disso.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

from app.services.recorder_xray import (
    _base,
    _cgi_pares,
    _pedir,
    detectar_marca,
)

# Campos de rede do CGI Dahua/Intelbras, em qualquer profundidade de chave
# (`table.Network.eth0.IPAddress`, `Network.eth0.IPAddress`, ...).
_CAMPO_REDE = re.compile(
    r"\.(IPAddress|SubnetMask|DefaultGateway|PhysicalAddress|DhcpEnable)\s*=\s*(\S+)",
    re.IGNORECASE,
)
_DE_PARA_REDE = {
    "ipaddress": "ip",
    "subnetmask": "mascara",
    "defaultgateway": "gateway",
    "physicaladdress": "mac",
    "dhcpenable": "dhcp",
}


def _xml(texto: str, tag: str) -> str:
    """Conteudo da primeira <tag>. Sem parser: o ISAPI usa namespace padrao e
    `ElementTree` obrigaria a prefixar cada busca.

    SEM IGNORECASE de proposito. O ISAPI distingue `<IPAddress>` (o elemento
    raiz da resposta de rede) de `<ipAddress>` (o valor). Buscando sem
    diferenciar, a raiz casava primeiro e o "IP da camera" vinha como o XML
    inteiro: `<ipVersion>v4</ipVersion>...<ipAddress>10.50.11.1`.
    """
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", texto or "", re.DOTALL)
    return (m.group(1) or "").strip() if m else ""


# --------------------------------------------------------------- Hikvision --
def _xray_hikvision(base: str, user: str, senha: str) -> Dict[str, Any]:
    cod, corpo = _pedir(f"{base}/ISAPI/System/deviceInfo", user, senha, timeout=8.0)
    if not cod or not (200 <= cod < 300):
        raise ValueError(
            "a camera respondeu no ISAPI mas recusou a credencial"
            if cod in (401, 403)
            else f"ISAPI devolveu {cod}"
        )
    equip = {
        "fabricante": "Hikvision",
        "nome": _xml(corpo, "deviceName"),
        "modelo": _xml(corpo, "model"),
        "serial": _xml(corpo, "serialNumber"),
        "firmware": " ".join(
            x for x in (_xml(corpo, "firmwareVersion"), _xml(corpo, "firmwareReleasedDate")) if x
        ),
        "mac": _xml(corpo, "macAddress"),
    }

    rede: Dict[str, str] = {"mac": equip.get("mac") or ""}
    _, net = _pedir(
        f"{base}/ISAPI/System/Network/interfaces/1/ipAddress", user, senha, timeout=8.0
    )
    if net:
        rede["ip"] = _xml(net, "ipAddress")
        rede["mascara"] = _xml(net, "subnetMask")
        # O gateway vem aninhado em <DefaultGateway><ipAddress>: a busca por
        # "ipAddress" acharia o endereco da camera de novo, entao recorta
        # primeiro o bloco do gateway.
        rede["gateway"] = _xml(_xml(net, "DefaultGateway"), "ipAddress")
        rede["dhcp"] = "sim" if _xml(net, "addressingType").lower() == "dynamic" else "nao"

    # O nome do dispositivo E o titulo nesta marca: e o que aparece no OSD e no
    # canal do gravador.
    return {"marca": "hikvision", "equipamento": equip, "rede": rede, "titulo": equip["nome"]}


# --------------------------------------------------------------- Intelbras --
def _magic(base: str, user: str, senha: str, acao: str) -> str:
    cod, corpo = _pedir(f"{base}/cgi-bin/magicBox.cgi?action={acao}", user, senha, timeout=6.0)
    if not cod or not (200 <= cod < 300):
        return ""
    # Respostas de uma linha so: `type=IPC-HDBW1200E`.
    texto = (corpo or "").strip()
    return texto.partition("=")[2].strip() if "=" in texto.splitlines()[0] else texto


def _xray_intelbras(base: str, user: str, senha: str) -> Dict[str, Any]:
    cod, corpo = _pedir(
        f"{base}/cgi-bin/magicBox.cgi?action=getSystemInfo", user, senha, timeout=8.0
    )
    if cod in (401, 403):
        raise ValueError("a camera respondeu mas recusou a credencial")
    if not cod:
        raise ValueError(f"a camera nao respondeu em {base}")

    pares = _cgi_pares(corpo) if 200 <= cod < 300 else {}
    equip = {
        "fabricante": _magic(base, user, senha, "getVendor") or "Intelbras",
        "nome": _magic(base, user, senha, "getMachineName"),
        "modelo": pares.get("deviceType") or _magic(base, user, senha, "getDeviceType"),
        "serial": pares.get("serialNumber") or _magic(base, user, senha, "getSerialNo"),
        "firmware": pares.get("version") or _magic(base, user, senha, "getSoftwareVersion"),
        "mac": "",
    }

    rede: Dict[str, str] = {}
    _, net = _pedir(
        f"{base}/cgi-bin/configManager.cgi?action=getConfig&name=Network", user, senha, timeout=8.0
    )
    for campo, valor in _CAMPO_REDE.findall(net or ""):
        chave = _DE_PARA_REDE[campo.lower()]
        rede.setdefault(chave, valor.strip())
    if rede.get("dhcp"):
        rede["dhcp"] = "sim" if rede["dhcp"].lower() in ("true", "1") else "nao"
    equip["mac"] = rede.get("mac") or ""

    titulo = ""
    _, tit = _pedir(
        f"{base}/cgi-bin/configManager.cgi?action=getConfig&name=ChannelTitle",
        user,
        senha,
        timeout=6.0,
    )
    for chave, valor in _cgi_pares(tit or "").items():
        if chave.lower().endswith(".name"):
            titulo = valor
            break

    return {"marca": "intelbras", "equipamento": equip, "rede": rede, "titulo": titulo}


# ------------------------------------------------------------------ achados --
def _achados(dados: Dict[str, Any], host: str) -> List[Tuple[str, str, str]]:
    """O que merece a atencao do tecnico ANTES de ele descer do poste."""
    saida: List[Tuple[str, str, str]] = []
    rede = dados.get("rede") or {}
    equip = dados.get("equipamento") or {}

    if rede.get("dhcp") == "sim":
        saida.append((
            "aviso",
            "A camera esta em DHCP",
            "O endereco pode mudar no proximo reboot e o gravador perde o canal. "
            "Fixe o IP antes de encerrar a instalacao.",
        ))
    if rede.get("ip") and host and rede["ip"] != host:
        saida.append((
            "info",
            "A camera se enxerga em outro endereco",
            f"Ela responde por {host}, mas diz estar em {rede['ip']}. "
            "Normal quando o acesso passa por NAT; confira se nao e IP duplicado.",
        ))
    if not equip.get("modelo"):
        saida.append((
            "aviso",
            "Modelo nao informado",
            "A camera respondeu mas nao disse o modelo. Preencha a mao para o relatorio nao sair vazio.",
        ))
    if not rede.get("mascara"):
        saida.append((
            "aviso",
            "Mascara de rede nao lida",
            "Sem mascara nao da para trocar o IP com seguranca -- chutar /24 ja tirou camera do ar.",
        ))
    return saida


# -------------------------------------------------------------------- API ---
def raio_x_camera(
    host: str, user: str, senha: str, porta: Any = None, connector_id: str = ""
) -> Dict[str, Any]:
    """Le tudo que a camera expoe. Levanta ValueError se nao conseguir entrar.

    Mesmo contrato do `recorder_xray.raio_x`: quem chama trata ValueError como
    recusa do equipamento (502) e qualquer outra excecao como erro nosso.
    """
    base = _base(host, porta, connector_id)
    marca = detectar_marca(base, user, senha)
    dados = (_xray_hikvision if marca == "hikvision" else _xray_intelbras)(base, user, senha)

    equip = dados.get("equipamento") or {}
    if not equip.get("modelo") and not equip.get("serial") and not dados.get("rede"):
        raise ValueError("a camera respondeu, mas nao devolveu nada util -- confira usuario e senha")

    dados["host"] = host
    dados["base"] = base
    dados["achados"] = _achados(dados, host)
    return dados


def gravar_titulo(
    host: str, user: str, senha: str, titulo: str, porta: Any = None, connector_id: str = ""
) -> Dict[str, Any]:
    """Grava o titulo na propria camera, nas DUAS marcas.

    A versao anterior so falava CGI Dahua/Intelbras, entao numa Hikvision ela
    falhava sempre -- e as cameras da TELHA, onde isto foi testado, sao todas
    Hikvision. Ali o nome do dispositivo e o titulo: e ele que aparece no OSD
    e no canal do gravador.
    """
    base = _base(host, porta, connector_id)
    marca = detectar_marca(base, user, senha)

    if marca == "hikvision":
        import xml.sax.saxutils as _x

        corpo = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<DeviceInfo version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">'
            f"<deviceName>{_x.escape(titulo)}</deviceName>"
            "</DeviceInfo>"
        )
        cod, resposta = _put(f"{base}/ISAPI/System/deviceInfo", user, senha, corpo)
        return {
            "ok": bool(cod and 200 <= cod < 300),
            "marca": marca,
            "status": cod,
            "response": (resposta or "")[:300],
        }

    url = (
        f"{base}/cgi-bin/configManager.cgi?action=setConfig"
        f"&ChannelTitle[0].Name={quote(titulo, safe='')}"
    )
    cod, resposta = _pedir(url, user, senha, timeout=8.0)
    texto = (resposta or "").strip()
    return {
        "ok": bool(cod and 200 <= cod < 300 and "error" not in texto.lower()),
        "marca": marca,
        "status": cod,
        "response": texto[:300],
    }


def _put(url: str, user: str, senha: str, corpo: str, timeout: float = 10.0) -> Tuple[Any, str]:
    """PUT com Digest e depois Basic -- o `_pedir` do gravador so faz GET."""
    import requests
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth

    for auth in (HTTPDigestAuth(user, senha), HTTPBasicAuth(user, senha)):
        try:
            r = requests.put(
                url,
                data=corpo.encode("utf-8"),
                auth=auth,
                timeout=timeout,
                verify=False,
                headers={"Content-Type": "application/xml"},
            )
            if r.status_code not in (401, 403):
                return r.status_code, (r.text or "")
        except Exception as exc:
            return None, str(exc)
    return 401, ""


def aplicar_ip(
    host: str,
    user: str,
    senha: str,
    novo_ip: str,
    porta: Any = None,
    connector_id: str = "",
    mascara: str = "",
    gateway: str = "",
) -> Dict[str, Any]:
    """Troca o IP da camera herdando mascara/gateway LIDOS dela.

    Nunca chuta mascara: /24 chutado em rede /23 ja tirou camera do ar, e
    camera sem rota nao se conserta pela rede -- alguem sobe no poste.
    """
    dados = raio_x_camera(host, user, senha, porta, connector_id)
    rede = dados.get("rede") or {}
    mascara = mascara or rede.get("mascara") or ""
    gateway = gateway or rede.get("gateway") or ""
    if not mascara:
        raise ValueError(
            "nao consegui ler a mascara atual da camera -- sem ela a troca de IP pode deixa-la inalcancavel"
        )

    base = dados["base"]
    if dados.get("marca") == "hikvision":
        corpo = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<IPAddress version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">'
            "<ipVersion>v4</ipVersion><addressingType>static</addressingType>"
            f"<ipAddress>{novo_ip}</ipAddress><subnetMask>{mascara}</subnetMask>"
            f"<DefaultGateway><ipAddress>{gateway}</ipAddress></DefaultGateway>"
            "</IPAddress>"
        )
        cod, resposta = _put(
            f"{base}/ISAPI/System/Network/interfaces/1/ipAddress", user, senha, corpo
        )
        ok = bool(cod and 200 <= cod < 300)
    else:
        params = [
            f"Network.eth0.IPAddress={novo_ip}",
            f"Network.eth0.SubnetMask={mascara}",
        ]
        if gateway:
            params.append(f"Network.eth0.DefaultGateway={gateway}")
        cod, resposta = _pedir(
            f"{base}/cgi-bin/configManager.cgi?action=setConfig&" + "&".join(params),
            user,
            senha,
            timeout=10.0,
        )
        ok = bool(cod and 200 <= cod < 300 and "error" not in (resposta or "").lower())

    return {
        "ok": ok,
        "marca": dados.get("marca"),
        "status": cod,
        "ip": host,
        "new_ip": novo_ip,
        "subnet_mask": mascara,
        "gateway": gateway,
        "response": (resposta or "").strip()[:300],
    }
