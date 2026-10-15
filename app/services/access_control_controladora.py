"""Ajustes de uma controladora de acesso (gaveta "Controladora" em Dispositivos).

Comandos da HTTP API Intelbras V3.59, pelo mesmo caminho que o resto do
controle de acesso usa (access_control_device._get: IP virtual do conector ou
job no conector, nunca o IP real de um conector isolado):

- leitura:  magicBox getDeviceType / getSoftwareVersion / getSerialNo (4.x),
            global.cgi getCurrentTime (4.6.2), configManager getConfig NTP;
- escrita:  global.cgi setCurrentTime (4.6.3), configManager setConfig NTP
            (fuso 22 = GMT-03:00), magicBox reboot, accessControl closeDoor
            (12.1.2; abrir ja existia em POST /devices/{id}/open-door).

Equipamento de cliente e vivo: escrita so acontece quando alguem clica, cada
uma e registrada no log com o usuario, e reiniciar exige admin.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException

FUSO_LOCAL = timezone(timedelta(hours=-3))
FUSO_INTELBRAS_BRASILIA = 22          # tabela de fusos do NTP: 22 = GMT-03:00
NTP_PADRAO = "a.ntp.br"
TOLERANCIA_SEGUNDOS = 120             # mais que isso, a hora do leitor esta errada
log = logging.getLogger("cam-snapshot")


def _t(v: Any) -> str:
    return str(v or "").strip()


def _leitor(device_id: str) -> Dict[str, Any]:
    from app.services.access_control_store import get_device_with_password
    d = get_device_with_password(_t(device_id))
    if not d:
        raise HTTPException(status_code=404, detail="Dispositivo nao encontrado neste cliente.")
    return d


def _kv(texto: str) -> Dict[str, str]:
    """'a=1\\nb=2' (ou 'table.NTP.Enable=true') -> {chave: valor}."""
    saida: Dict[str, str] = {}
    for linha in (texto or "").splitlines():
        if "=" in linha:
            k, v = linha.split("=", 1)
            saida[k.strip().removeprefix("table.")] = v.strip()
    return saida


def _ler(device: Dict[str, Any], path: str, params: Dict[str, Any], get=None) -> Dict[str, str]:
    from app.services.access_control_device import _check_device_response, _get
    get = get or _get
    return _kv(_check_device_response(get(device, path, params), "a leitura"))


def _parse_hora(texto: str) -> Optional[datetime]:
    t = _t(texto).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H-%M-%S"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


def _agora_local(agora: Optional[datetime] = None) -> datetime:
    return (agora or datetime.now(timezone.utc)).astimezone(FUSO_LOCAL).replace(tzinfo=None, microsecond=0)


def diagnostico(device_id: str, get: Optional[Callable] = None, agora: Optional[datetime] = None) -> Dict[str, Any]:
    """So leitura. Cada pergunta ao leitor e independente: uma que falhar nao
    esconde as outras (firmware antigo nao responde todas)."""
    d = _leitor(device_id)
    resultado: Dict[str, Any] = {"ok": True, "id": _t(d.get("id")), "nome": _t(d.get("name")), "erros": {}}
    perguntas = {
        "tipo": ("/cgi-bin/magicBox.cgi", {"action": "getDeviceType"}),
        "firmware": ("/cgi-bin/magicBox.cgi", {"action": "getSoftwareVersion"}),
        "serie": ("/cgi-bin/magicBox.cgi", {"action": "getSerialNo"}),
        "hora": ("/cgi-bin/global.cgi", {"action": "getCurrentTime"}),
        "ntp": ("/cgi-bin/configManager.cgi", {"action": "getConfig", "name": "NTP"}),
        "porta": ("/cgi-bin/accessControl.cgi", {"action": "getDoorStatus", "channel": 1}),
    }
    respostas: Dict[str, Dict[str, str]] = {}
    for chave, (path, params) in perguntas.items():
        try:
            respostas[chave] = _ler(d, path, params, get)
        except HTTPException as exc:
            resultado["erros"][chave] = _t(exc.detail)
        except Exception as exc:   # um comando nao derruba a leitura inteira
            resultado["erros"][chave] = _t(exc) or exc.__class__.__name__
    if len(resultado["erros"]) == len(perguntas):
        primeiro = next(iter(resultado["erros"].values()))
        raise HTTPException(status_code=502, detail=f"O leitor nao respondeu: {primeiro}")
    resultado["modelo"] = respostas.get("tipo", {}).get("type", "")
    resultado["firmware"] = " ".join(x for x in (respostas.get("firmware", {}).get("version", ""),) if x)
    resultado["serie"] = respostas.get("serie", {}).get("sn", "")
    hora_txt = respostas.get("hora", {}).get("result", "")
    hora = _parse_hora(hora_txt)
    certa = _agora_local(agora)
    resultado["hora_leitor"] = hora.strftime("%Y-%m-%d %H:%M:%S") if hora else hora_txt
    resultado["hora_certa"] = certa.strftime("%Y-%m-%d %H:%M:%S")
    if hora:
        dif = int((hora - certa).total_seconds())
        resultado["diferenca_segundos"] = dif
        resultado["hora_ok"] = abs(dif) <= TOLERANCIA_SEGUNDOS
    estado = respostas.get("porta", {}).get("Info.status", "")
    resultado["porta"] = {"Open": "aberta", "Close": "fechada", "Break": "forcada"}.get(estado, estado.lower())
    ntp = respostas.get("ntp", {})
    if ntp:
        resultado["ntp"] = {
            "ativo": ntp.get("NTP.Enable", "").lower() == "true",
            "servidor": ntp.get("NTP.Address", ""),
            "fuso": ntp.get("NTP.TimeZone", ""),
            "fuso_desc": ntp.get("NTP.TimeZoneDesc", ""),
            "fuso_ok": ntp.get("NTP.TimeZone", "") == str(FUSO_INTELBRAS_BRASILIA),
        }
    return resultado


def acertar_hora(device_id: str, usuario: str, get: Optional[Callable] = None,
                 agora: Optional[datetime] = None) -> Dict[str, Any]:
    from app.services.access_control_device import _check_device_response, _get
    get = get or _get
    d = _leitor(device_id)
    certa = _agora_local(agora).strftime("%Y-%m-%d %H:%M:%S")
    _check_device_response(get(d, "/cgi-bin/global.cgi", {"action": "setCurrentTime", "time": certa}), "o acerto da hora")
    log.info("controladora %s (%s): hora acertada para %s por %s", d.get("id"), d.get("name"), certa, usuario)
    return {"ok": True, "hora": certa}


def configurar_ntp(device_id: str, usuario: str, servidor: str = NTP_PADRAO, ativar: bool = True,
                   get: Optional[Callable] = None) -> Dict[str, Any]:
    from app.services.access_control_device import _check_device_response, _get
    get = get or _get
    servidor = _t(servidor) or NTP_PADRAO
    if len(servidor) > 120 or any(c in servidor for c in " /?&#="):
        raise HTTPException(status_code=400, detail="Servidor de hora invalido.")
    d = _leitor(device_id)
    params = {"action": "setConfig", "NTP.Enable": "true" if ativar else "false"}
    if ativar:
        params.update({"NTP.Address": servidor, "NTP.Port": "123", "NTP.TimeZone": str(FUSO_INTELBRAS_BRASILIA)})
    _check_device_response(get(d, "/cgi-bin/configManager.cgi", params), "a configuracao do NTP")
    log.info("controladora %s (%s): NTP %s (%s) por %s", d.get("id"), d.get("name"),
             "ligado" if ativar else "desligado", servidor, usuario)
    return {"ok": True, "ativo": ativar, "servidor": servidor if ativar else ""}


def reiniciar(device_id: str, usuario: str, get: Optional[Callable] = None) -> Dict[str, Any]:
    from app.services.access_control_device import _check_device_response, _get
    get = get or _get
    d = _leitor(device_id)
    _check_device_response(get(d, "/cgi-bin/magicBox.cgi", {"action": "reboot"}), "o reinicio")
    log.info("controladora %s (%s): reiniciada por %s", d.get("id"), d.get("name"), usuario)
    return {"ok": True}


def fechar_porta(device_id: str, usuario: str, canal: int = 1, get: Optional[Callable] = None) -> Dict[str, Any]:
    """Fecha (trava) a porta agora. Par do POST /devices/{id}/open-door."""
    from app.services.access_control_device import _check_device_response, _get
    get = get or _get
    d = _leitor(device_id)
    _check_device_response(get(d, "/cgi-bin/accessControl.cgi",
                               {"action": "closeDoor", "channel": int(canal or 1), "UserID": "SightOps", "Type": "Remote"}),
                           "fechar a porta")
    log.info("controladora %s (%s): porta %s fechada remotamente por %s", d.get("id"), d.get("name"), canal, usuario)
    return {"ok": True}
