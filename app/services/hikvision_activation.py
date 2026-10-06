"""Ativacao de camera Hikvision pelo ISAPI.

Por que existe separado do NetSDK: a tela de Ativacao de Cameras foi construida
sobre o `CLIENT_InitDevAccountByIP` do SDK da Intelbras, que so conversa com
equipamento Dahua/Intelbras. Uma Hikvision de fabrica nao responde a esse SDK,
entao a tela simplesmente nao a enxergava -- dava "nenhuma camera varrida" com
a camera ligada na frente.

Como a Hikvision marca "de fabrica": sem senha definida o equipamento responde
`GET /ISAPI/Security/userCheck` SEM autenticacao, dizendo que nao esta ativado.
Depois de ativada, a mesma rota passa a exigir credencial. Conferido na
IPC-B121H-C (firmware V5.8.10) da TELHA: 401 sem senha, e 200 `<statusString>OK`
com senha -- ou seja, ja ativada.

LIMITE CONHECIDO: a parte de ESCREVER (ativar) nao pode ser conferida sem uma
camera de fabrica na mao, e no parque de hoje nao existe nenhuma -- as 31 da
TELHA estao todas ativadas. O caminho implementado e o `PUT /ISAPI/System/activate`
com a senha em texto. Firmware mais novo pode exigir o handshake cifrado de
`/ISAPI/Security/challenge` (essa rota responde sem autenticacao, entao existe);
nesse caso o equipamento RECUSA e continua de fabrica -- nao fica com senha
desconhecida. O erro do equipamento e devolvido como veio, para o proximo
tecnico saber o que aconteceu em vez de ver "falhou".
"""
from __future__ import annotations

import re
import xml.sax.saxutils as _x
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

import requests
import urllib3

urllib3.disable_warnings()

# Curto de proposito: a varredura passa por dezenas de enderecos, a maioria sem
# nada atras. Quem responde, responde rapido.
_TEMPO_SONDA = 4.0
# O IP de fabrica e o mesmo para todas: quando uma sai dele (DHCP + reboot),
# o MikroTik segue mandando para o MAC dela ate o ARP "stale" vencer e ele
# perguntar de novo -- uns 5 a 10 s. Com 4 s a sonda desistia antes e a
# proxima camera de fabrica ficava invisivel ate alguem pingar de dentro do
# MikroTik (SIERRA, 06/10/2026, com 2 no .64). So nesse IP, e so se a primeira
# sonda nao teve resposta, tenta de novo dando tempo do ARP se refazer.
_IPS_DE_FABRICA = {"192.168.1.64"}
_TEMPO_SONDA_FABRICA = 20.0
_TEMPO_ATIVACAO = 20.0
_PARALELO = 12


def _campo(xml: str, nome: str) -> str:
    m = re.search(rf"<{nome}>([^<]*)</{nome}>", xml or "", re.I)
    return (m.group(1).strip() if m else "")


def _get(url: str, timeout: float) -> Tuple[int, str, str]:
    """(codigo, corpo, desafio) -- o desafio e o cabecalho WWW-Authenticate."""
    try:
        r = requests.get(url, timeout=timeout, verify=False)
        return r.status_code, (r.text or ""), (r.headers.get("WWW-Authenticate") or "")
    except Exception:
        return 0, "", ""


def sondar(base: str, ip_real: str = "") -> Dict[str, Any]:
    """Diz se ha uma Hikvision neste endereco e se ela ainda e de fabrica.

    O MARCADOR, e ele e explicito: `GET /ISAPI/Security/userCheck` SEM
    autenticacao devolve, numa camera de fabrica, HTTP 200 com
    `<isActivated>false</isActivated>`. Numa camera que ja tem senha a mesma
    rota devolve 401 e nada mais.

    MEDIDO na TELHA, 47 enderecos: 34 responderam 401 (ativadas), 1 respondeu
    200 com isActivated=false (a camera nova em 192.168.1.64) e 12 nao
    responderam. Zero ambiguidade.

    POR QUE ISSO DEMOROU A APARECER: enquanto a camera esta BLOQUEADA por
    tentativa errada ela responde 403 em tudo, inclusive aqui -- e foi assim
    que eu a encontrei nas primeiras sondas, o que me levou a dois marcadores
    errados antes deste. Bloqueio nao e estado de ativacao: 403 agora e
    reportado como "travada", nao como "de fabrica", porque acontece com
    qualquer camera e passa sozinho (ou tirando e pondo a energia).

    UMA requisicao por endereco (duas so na de fabrica, para tentar ler modelo
    e MAC). Isso importa: e a sonda repetida que bloqueia o equipamento.
    """
    cod, corpo, _ = _get(f"{base}/ISAPI/Security/userCheck", _TEMPO_SONDA)
    if not cod and ip_real in _IPS_DE_FABRICA:
        cod, corpo, _ = _get(f"{base}/ISAPI/Security/userCheck", _TEMPO_SONDA_FABRICA)
    if not cod:
        return {"presente": False}

    if cod == 403:
        return {"presente": True, "ativada": None, "travada": True,
                "vendor": "Hikvision"}

    if 200 <= cod < 300:
        marca = re.search(r"<isActivated>([^<]*)</isActivated>", corpo or "", re.I)
        if not marca:
            # Respondeu sem exigir senha e sem declarar o estado: trata como
            # ativada, que e o caso conservador (nao oferece ativar).
            return {"presente": True, "ativada": True, "vendor": "Hikvision"}

        de_fabrica = marca.group(1).strip().lower() in ("false", "0", "no")
        dados: Dict[str, Any] = {"presente": True, "ativada": not de_fabrica,
                                 "vendor": "Hikvision"}
        if de_fabrica:
            # Em firmware antigo o deviceInfo abre sem senha e ja traz modelo,
            # MAC e firmware. No V5.8.10 ele recusa -- as colunas ficam vazias,
            # o que e honesto: nao da para saber antes de ativar.
            cod2, corpo2, _ = _get(f"{base}/ISAPI/System/deviceInfo", _TEMPO_SONDA)
            if cod2 and 200 <= cod2 < 300 and "<DeviceInfo" in (corpo2 or ""):
                dados.update({
                    "model": _campo(corpo2, "model"),
                    "mac": _campo(corpo2, "macAddress"),
                    "firmware": _campo(corpo2, "firmwareVersion"),
                    "serial": _campo(corpo2, "serialNumber"),
                    "device_name": _campo(corpo2, "deviceName"),
                })
        return dados

    if cod == 401:
        # Pediu senha: existe conta de admin, logo ja foi ativada.
        return {"presente": True, "ativada": True, "vendor": "Hikvision"}

    return {"presente": False}


def _como_dispositivo(ip_real: str, achado: Dict[str, Any],
                      mac_da_rede: str = "") -> Dict[str, Any]:
    """No mesmo formato do NetSDK, para a tela nao precisar saber de marca."""
    ativada = achado.get("ativada")
    de_fabrica = ativada is False
    indefinido = ativada is None
    return {
        "ip": ip_real,
        # Camera JA ativada nao entrega o MAC sem senha -- mas o roteador do site
        # sabe, porque ele resolveu ARP para falar com ela. Dado de graca.
        "mac": achado.get("mac") or mac_da_rede or "",
        "model": achado.get("model", ""),
        "serial": achado.get("serial", ""),
        "firmware": achado.get("firmware", ""),
        "device_name": achado.get("device_name", ""),
        "http_port": 80,
        "port": 8000,
        "dhcp": False,
        "subnet_mask": "",
        "gateway": "",
        "vendor": "Hikvision",
        # Numero, nao texto: a tela compara com os codigos do NetSDK
        # (0 = nao da para saber, 1 = de fabrica, 2 = ja inicializada).
        "init_status": 0 if indefinido else (1 if de_fabrica else 2),
        "needs_activation": de_fabrica,
        "estado_indefinido": indefinido,
        # Camera travada pode ser tentada: se o bloqueio ja tiver passado, ativa.
        "pode_tentar": indefinido,
        "travada": bool(achado.get("travada")),
        # A Hikvision nao pede telefone nem e-mail para ativar: a senha basta.
        "pwd_reset_way": 0,
        "needs_phone": False,
        "needs_email": False,
    }


def procurar(por_virtual: Dict[str, str], macs: Dict[str, str] = None) -> List[Dict[str, Any]]:
    """Sonda varios enderecos de uma vez. `por_virtual` e {ip_virtual: ip_real}.

    Os IPs virtuais ja vem resolvidos de fora: o contexto do cliente nao
    atravessa o ThreadPoolExecutor, entao nada aqui dentro pode consultar
    tenant nem conector.
    """
    alvos = list(por_virtual.items())
    achados: List[Dict[str, Any]] = []
    if not alvos:
        return achados
    with ThreadPoolExecutor(max_workers=_PARALELO) as pool:
        for (virtual, real), achado in zip(
                alvos, pool.map(lambda t: sondar(f"http://{t[0]}", t[1]), alvos)):
            if achado.get("presente"):
                achados.append(_como_dispositivo(
                    real, achado, (macs or {}).get(real, "")))
    return achados


def dados_apos_ativar(base: str, senha: str) -> Dict[str, Any]:
    """Modelo, MAC e firmware -- lidos DEPOIS de ativar, com a senha nova.

    Antes de ativar a camera nao conta nada disso (o deviceInfo responde 401 no
    firmware novo), e sem o MAC a senha nao tem como ser guardada no cofre por
    equipamento, so como padrao do site. Como a ativacao acabou de criar a
    conta, aqui ela abre.
    """
    cod, corpo, _ = _get_auth(f"{base}/ISAPI/System/deviceInfo", senha)
    if not cod or not (200 <= cod < 300):
        return {}
    return {
        "mac": _campo(corpo, "macAddress"),
        "model": _campo(corpo, "model"),
        "firmware": _campo(corpo, "firmwareVersion"),
        "serial": _campo(corpo, "serialNumber"),
        "device_name": _campo(corpo, "deviceName"),
    }


def _get_auth(url: str, senha: str, usuario: str = "admin"):
    """GET autenticado. Digest primeiro, basic depois -- igual ao resto do app."""
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth
    for auth in (HTTPDigestAuth(usuario, senha), HTTPBasicAuth(usuario, senha)):
        try:
            r = requests.get(url, auth=auth, timeout=_TEMPO_SONDA, verify=False)
            if r.status_code not in (401, 403):
                return r.status_code, (r.text or ""), ""
        except Exception:
            continue
    return 0, "", ""


def ativar(base: str, senha: str) -> Dict[str, Any]:
    """Cria a senha de admin numa Hikvision de fabrica, pelo HCNetSDK.

    NAO da para fazer por HTTP: `PUT /ISAPI/System/activate` com a senha em
    texto responde `badParameters` sempre. O equipamento exige um handshake --
    o bundle da propria camera mostra o caminho (RSA do cliente ->
    `POST /ISAPI/Security/challenge` -> senha cifrada em AES com o segredo que
    volta). `NET_DVR_ActivateDevice` faz isso por dentro.

    Provado em 02/10/2026 contra a camera de fabrica da TELHA: com senha fraca
    de teste o SDK devolveu 251 (`NET_DVR_ERROR_RISK_PASSWORD`), ou seja chegou
    na camera, negociou, e foi o EQUIPAMENTO que recusou a senha.

    Roda em subprocesso: ver `hikvision_netsdk.ativar_isolado`.
    """
    from app.services import hikvision_netsdk as netsdk

    if not netsdk.available():
        return {"ok": False,
                "error": "o SDK da Hikvision nao esta instalado neste servidor"}

    # O IP virtual sai do `base` montado por quem chamou (http://10.210.x.y).
    alvo = base.replace("https://", "").replace("http://", "").split("/")[0]
    alvo = alvo.split(":")[0]

    # Porta 8000 (protocolo proprietario). Pela 80/ISAPI o SDK devolveu erro
    # generico de transporte na mesma camera -- a 8000 e a que responde direito.
    r = netsdk.ativar_isolado(alvo, senha, porta=8000, modo=netsdk.LOGIN_PRIVADO)
    if r.get("ok"):
        return {"ok": True, "usuario": "admin", **dados_apos_ativar(base, senha)}

    codigo = r.get("codigo")
    if r.get("ja_ativada") or codigo == netsdk.ERRO_JA_ATIVADA:
        return {"ok": False, "ja_ativada": True,
                "error": "essa camera ja estava ativada"}
    if codigo == 251:
        return {"ok": False, "senha_fraca": True,
                "error": "a camera recusou a senha por ser fraca -- use de 8 a 15 "
                         "caracteres com maiuscula, minuscula, numero e simbolo"}
    return r


def definir_perguntas(base: str, senha: str, perguntas) -> Dict[str, Any]:
    """Grava as perguntas de recuperacao. `perguntas` = [(id, resposta), ...].

    Por ISAPI, com a senha de admin DENTRO do corpo -- sem o `<password>` o
    equipamento responde 400. Provado na IPC-B121H-C da TELHA: as perguntas
    1, 2 e 3 passaram a `mark: true`.

    Nao e pelo SDK porque este modelo nao suporta os comandos de pergunta
    (4363 a 4366): ate a leitura devolve PARAMETER_ERROR.

    ARMADILHA: durante o boot (ou logo apos um reset) a camera responde 403
    `Invalid Operation` a QUALQUER escrita -- inclusive esta e a de rede. Nao e
    falta de permissao, e a camera ainda subindo. Vale esperar e repetir.
    """
    if not perguntas:
        return {"ok": True, "gravadas": 0}

    itens = "".join(
        f"<Question><id>{int(pid)}</id><answer>{_x.escape(str(resp))}</answer></Question>"
        for pid, resp in perguntas
    )
    corpo = ("<?xml version='1.0' encoding='UTF-8'?><SecurityQuestion><QuestionList>"
             f"{itens}</QuestionList><password>{_x.escape(senha)}</password>"
             "</SecurityQuestion>")
    cod, texto = _put_auth(f"{base}/ISAPI/Security/questionConfiguration", senha, corpo)
    if cod and 200 <= cod < 300 and _campo(texto, "statusString").lower() in ("ok", "success", ""):
        return {"ok": True, "gravadas": len(perguntas)}
    detalhe = _campo(texto, "subStatusCode") or _campo(texto, "statusString") or f"HTTP {cod}"
    return {"ok": False, "error": f"a camera recusou as perguntas ({detalhe})"}


def definir_dhcp(base: str, senha: str) -> Dict[str, Any]:
    """Poe a camera em DHCP, para ela sair do IP de fabrica e entrar na faixa
    do site. So vale depois do proximo boot: a camera guarda a configuracao mas
    so pede endereco ao reiniciar."""
    corpo = ("<?xml version='1.0' encoding='UTF-8'?>"
             "<IPAddress version='2.0' xmlns='http://www.hikvision.com/ver20/XMLSchema'>"
             "<ipVersion>v4</ipVersion><addressingType>dynamic</addressingType></IPAddress>")
    cod, texto = _put_auth(
        f"{base}/ISAPI/System/Network/interfaces/1/ipAddress", senha, corpo)
    if cod and 200 <= cod < 300:
        return {"ok": True, "precisa_reiniciar": True}
    detalhe = _campo(texto, "subStatusCode") or _campo(texto, "statusString") or f"HTTP {cod}"
    return {"ok": False, "error": f"a camera recusou o DHCP ({detalhe})"}


def reiniciar(base: str, senha: str) -> Dict[str, Any]:
    """Reinicia a camera -- e o que faz o DHCP valer."""
    cod, texto = _put_auth(f"{base}/ISAPI/System/reboot", senha, "", metodo="PUT")
    if cod and 200 <= cod < 300:
        return {"ok": True}
    return {"ok": False, "error": f"nao consegui reiniciar (HTTP {cod})"}


def _put_auth(url: str, senha: str, corpo: str, usuario: str = "admin",
              metodo: str = "PUT"):
    """Escrita autenticada. Digest primeiro, basic depois."""
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth
    for auth in (HTTPDigestAuth(usuario, senha), HTTPBasicAuth(usuario, senha)):
        try:
            r = requests.request(
                metodo, url, auth=auth, data=corpo.encode("utf-8") if corpo else None,
                headers={"Content-Type": "application/xml"} if corpo else None,
                timeout=20, verify=False)
            if r.status_code not in (401, 403):
                return r.status_code, (r.text or "")
            ultimo = (r.status_code, (r.text or ""))
        except Exception:
            ultimo = (0, "")
    return ultimo
