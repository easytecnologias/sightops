"""Usuario ONVIF de camera Hikvision, pelo ISAPI (conector + IP virtual).

Para que serve: por camera Hikvision em gravador de outra marca (Intelbras e
afins), que puxa o video por ONVIF. A camera precisa do ONVIF LIGADO e de um
usuario ONVIF proprio -- o admin da camera nao serve para ONVIF.

Lido em 26/10/2026 numa IPC-B121H-L (172.16.45.101, INTERBLOCOS, firmware
V5.7.2): /ISAPI/System/Network/Integrate com <ONVIF><enable>false</enable>,
/ISAPI/Security/ONVIF/users com a lista vazia, e o capabilities dizendo ate 32
usuarios, nome 1..32, senha 1..16, perfis administrator/operator/mediaUser.

EQUIPAMENTO VIVO: ligar, criar e apagar gravam na camera do cliente. Toda
escrita e conferida relendo a camera -- o status HTTP sozinho nao prova nada.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple
from xml.sax.saxutils import escape

from app.services.camera_xray import _put
from app.services.recorder_xray import _base, _pedir, _postar

PERFIS = ("administrator", "operator", "mediaUser")
_NS_PADRAO = "http://www.isapi.org/ver20/XMLSchema"


def _apagar(url: str, user: str, senha: str, timeout: float = 10.0) -> Tuple[Any, str]:
    import requests
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth

    for auth in (HTTPDigestAuth(user, senha), HTTPBasicAuth(user, senha)):
        try:
            r = requests.delete(url, auth=auth, timeout=timeout, verify=False)
            if r.status_code not in (401, 403):
                return r.status_code, (r.text or "")
        except Exception as exc:
            return None, str(exc)
    return 401, ""


def _tag(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml or "", re.S)
    return (m.group(1) if m else "").strip()


def _ok(cod: Any, corpo: str, oque: str) -> None:
    """ResponseStatus da Hikvision: statusCode 1 = feito. Sem ele, so o HTTP."""
    if cod is None:
        raise ValueError(f"a camera nao respondeu ao {oque}: {corpo[:120]}")
    if cod == 401:
        raise ValueError("a camera recusou usuario e senha de admin")
    status = _tag(corpo, "statusCode")
    if (status and status != "1") or not (200 <= int(cod) < 300):
        motivo = _tag(corpo, "subStatusCode") or _tag(corpo, "statusString") or f"HTTP {cod}"
        raise ValueError(f"a camera recusou o {oque}: {motivo}")


def ler(host: str, user: str, senha: str, connector_id: str = "", porta: Any = None) -> Dict[str, Any]:
    """Estado do ONVIF e usuarios ONVIF. So leitura."""
    base = _base(host, porta, connector_id)  # recusa IP fora das redes do conector
    cod, integ = _pedir(f"{base}/ISAPI/System/Network/Integrate", user, senha, timeout=8.0)
    if cod == 401:
        raise ValueError("a camera recusou usuario e senha de admin")
    if cod is None:
        raise ValueError(f"a camera nao respondeu: {integ[:120]}")
    if cod != 200 or "<ONVIF>" not in (integ or ""):
        raise ValueError("esta camera nao tem ONVIF pelo ISAPI (so Hikvision e compativeis)")
    onvif = _tag(_tag(integ, "ONVIF"), "enable").lower() == "true"
    cod, lista = _pedir(f"{base}/ISAPI/Security/ONVIF/users", user, senha, timeout=8.0)
    # Escrever no MESMO namespace que a camera usa (a IPC-B121H-L responde
    # hikvision.com/ver20; firmware mais novo, isapi.org).
    ns = re.search(r'xmlns="([^"]+)"', lista or integ or "")
    usuarios: List[Dict[str, str]] = []
    if cod == 200:
        for bloco in re.findall(r"<User>(.*?)</User>", lista or "", re.S):
            usuarios.append({"id": _tag(bloco, "id"), "nome": _tag(bloco, "userName"),
                             "perfil": _tag(bloco, "userType")})
    cod, cap = _pedir(f"{base}/ISAPI/Security/ONVIF/users/capabilities", user, senha, timeout=8.0)
    senha_max = 16
    m = re.search(r'<passwordLen[^>]*max="(\d+)"', cap or "") if cod == 200 else None
    if m:
        senha_max = int(m.group(1))
    return {"host": host, "onvif_ligado": onvif, "usuarios": usuarios, "senha_max": senha_max,
            "perfis": list(PERFIS), "_ns": ns.group(1) if ns else _NS_PADRAO}


def ligar(host: str, user: str, senha: str, ligado: bool = True, connector_id: str = "",
          porta: Any = None) -> Dict[str, Any]:
    """Liga (ou desliga) o ONVIF, mexendo SO no bloco <ONVIF> do Integrate."""
    base = _base(host, porta, connector_id)
    cod, integ = _pedir(f"{base}/ISAPI/System/Network/Integrate", user, senha, timeout=8.0)
    if cod != 200 or "<ONVIF>" not in (integ or ""):
        raise ValueError("esta camera nao tem ONVIF pelo ISAPI")
    bloco = _tag(integ, "ONVIF")
    novo_bloco = re.sub(r"<enable>.*?</enable>", f"<enable>{'true' if ligado else 'false'}</enable>", bloco, count=1)
    corpo = integ.replace(f"<ONVIF>{bloco}</ONVIF>", f"<ONVIF>{novo_bloco}</ONVIF>", 1) \
        if f"<ONVIF>{bloco}</ONVIF>" in integ else re.sub(
            r"(<ONVIF>.*?<enable>).*?(</enable>)", rf"\g<1>{'true' if ligado else 'false'}\g<2>", integ, count=1, flags=re.S)
    cod, resp = _put(f"{base}/ISAPI/System/Network/Integrate", user, senha, corpo)
    _ok(cod, resp, "ligar o ONVIF" if ligado else "desligar o ONVIF")
    lido = ler(host, user, senha, connector_id, porta)
    if lido["onvif_ligado"] != ligado:
        raise ValueError("a camera aceitou, mas o ONVIF continua " + ("desligado" if ligado else "ligado"))
    return lido


def criar_usuario(host: str, user: str, senha: str, nome: str, senha_onvif: str, perfil: str = "administrator",
                  connector_id: str = "", porta: Any = None) -> Dict[str, Any]:
    """Cria o usuario ONVIF; se ja existe com o mesmo nome, troca senha e perfil."""
    nome, perfil = (nome or "").strip(), (perfil or "administrator").strip()
    if not nome or len(nome) > 32 or not re.fullmatch(r"[A-Za-z0-9_.\-@]+", nome):
        raise ValueError("nome do usuario ONVIF: 1 a 32 letras, numeros ou _ . - @")
    if perfil not in PERFIS:
        raise ValueError(f"perfil invalido: use {', '.join(PERFIS)}")
    antes = ler(host, user, senha, connector_id, porta)
    if not senha_onvif or len(senha_onvif) > antes["senha_max"]:
        raise ValueError(f"senha do usuario ONVIF: 1 a {antes['senha_max']} caracteres nesta camera")
    base = _base(host, porta, connector_id)
    existente = next((u for u in antes["usuarios"] if u["nome"] == nome), None)
    uid = existente["id"] if existente else str(1 + max([int(u["id"]) for u in antes["usuarios"] if u["id"].isdigit()] or [0]))
    corpo = (f'<User version="2.0" xmlns="{escape(antes["_ns"])}"><id>{escape(uid)}</id><userName>{escape(nome)}</userName>'
             f'<password>{escape(senha_onvif)}</password><userType>{escape(perfil)}</userType></User>')
    if existente:
        cod, resp = _put(f"{base}/ISAPI/Security/ONVIF/users/{uid}", user, senha, corpo)
    else:
        cod, resp = _postar(f"{base}/ISAPI/Security/ONVIF/users", user, senha, corpo)
    _ok(cod, resp, "atualizar o usuario ONVIF" if existente else "criar o usuario ONVIF")
    depois = ler(host, user, senha, connector_id, porta)
    if not any(u["nome"] == nome for u in depois["usuarios"]):
        raise ValueError("a camera aceitou, mas o usuario ONVIF nao aparece na lista")
    depois["acao"] = "atualizado" if existente else "criado"
    return depois


def apagar_usuario(host: str, user: str, senha: str, uid: str, connector_id: str = "",
                   porta: Any = None) -> Dict[str, Any]:
    if not str(uid or "").isdigit():
        raise ValueError("id do usuario ONVIF invalido")
    base = _base(host, porta, connector_id)
    cod, resp = _apagar(f"{base}/ISAPI/Security/ONVIF/users/{uid}", user, senha)
    _ok(cod, resp, "apagar o usuario ONVIF")
    depois = ler(host, user, senha, connector_id, porta)
    if any(u["id"] == str(uid) for u in depois["usuarios"]):
        raise ValueError("a camera aceitou, mas o usuario continua na lista")
    return depois


def preparar_para_gravador(host: str, user: str, senha: str, nome: str, senha_onvif: str,
                           perfil: str = "administrator", connector_id: str = "",
                           porta: Any = None) -> Dict[str, Any]:
    """O que o gravador de outra marca precisa: ONVIF ligado + o usuario. Usado
    na camera e no lote. So escreve o que falta."""
    passos: List[str] = []
    estado = ler(host, user, senha, connector_id, porta)
    if not estado["onvif_ligado"]:
        estado = ligar(host, user, senha, True, connector_id, porta)
        passos.append("ONVIF ligado")
    estado = criar_usuario(host, user, senha, nome, senha_onvif, perfil, connector_id, porta)
    passos.append(f"usuario {nome} {estado.get('acao', 'criado')}")
    estado["passos"] = passos
    return estado
