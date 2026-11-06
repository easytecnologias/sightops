"""Executa as automacoes do Alerta Termico: speed vai ao preset e saida de alarme
liga refletor/sirene (Hikvision/HikMicro, ISAPI).

Em modo 'simular' nada sai para a rede: so registra "faria X". Em 'valer' cada
acao fica no historico com a resposta do equipamento, porque falha aqui e
silenciosa no campo (a sirene nao toca e ninguem sabe).

Roda numa thread propria: nao pode segurar a leitura das cameras.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Tuple

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import automacao_store

logger = logging.getLogger(__name__)

TEMPO_S = 6.0
ESPERA_DESLIGAR_S = 5.0


def _put(url: str, usuario: str, senha: str, corpo: str = "") -> Tuple[int, str]:
    r = None
    for auth in (HTTPDigestAuth(usuario, senha), HTTPBasicAuth(usuario, senha)):
        r = requests.put(url, data=corpo.encode("utf-8"), auth=auth, timeout=TEMPO_S, verify=False,
                         headers={"Content-Type": "application/xml"})
        if r.status_code not in (401, 403):
            break
    return (r.status_code, r.text) if r is not None else (0, "")


def _alvo(acao: Dict[str, Any]) -> Tuple[str, Dict[str, str]]:
    from app.services.camera_credentials import resolve_camera_credential
    from app.services.connector_routing_vnat import set_olt_reach_connector
    from app.services.recorder_xray import _base

    eq = automacao_store.equipamento_do_inventario(acao.get("ip") or "", acao.get("connector_id") or "")
    if not eq:
        raise ValueError("equipamento saiu do inventário")
    cred = resolve_camera_credential(eq["mac"], eq["site"])
    if not cred:
        raise ValueError("sem usuário e senha salvos para este equipamento")
    set_olt_reach_connector("")      # a de cima pode ter deixado outro conector no contexto
    return _base(eq["ip"], eq["porta"], eq["connector_id"]), cred


def _posicao(base: str, cred: Dict[str, str]) -> Tuple[int, int, int]:
    r = requests.get(f"{base}/ISAPI/PTZCtrl/channels/1/status", auth=HTTPDigestAuth(cred["username"], cred["password"]),
                     timeout=TEMPO_S, verify=False)
    return tuple(int(re.search(rf"<{k}>(-?\d+)", r.text).group(1)) for k in ("elevation", "azimuth", "absoluteZoom"))


def _voltar_speed(tenant: str, acao: Dict[str, Any], pos: Tuple[int, int, int]) -> None:
    token = set_current_tenant_slug(tenant)
    try:
        base, cred = _alvo(acao)
        corpo = (f'<?xml version="1.0" encoding="UTF-8"?><PTZData><AbsoluteHigh><elevation>{pos[0]}</elevation>'
                 f'<azimuth>{pos[1]}</azimuth><absoluteZoom>{pos[2]}</absoluteZoom></AbsoluteHigh></PTZData>')
        cod, txt = _put(f"{base}/ISAPI/PTZCtrl/channels/1/absolute", cred["username"], cred["password"], corpo)
        if cod != 200:
            logger.error("automacao: speed %s NAO voltou: HTTP %s %s", acao.get("ip"), cod, txt[:120])
    except Exception as exc:
        logger.error("automacao: speed %s NAO voltou: %s", acao.get("ip"), exc)
    finally:
        reset_current_tenant_slug(token)


def _saida_estado(tenant: str, acao: Dict[str, Any], estado: str) -> Tuple[bool, str]:
    base, cred = _alvo(acao)
    corpo = f'<?xml version="1.0" encoding="UTF-8"?><IOPortData><outputState>{estado}</outputState></IOPortData>'
    cod, txt = _put(f"{base}/ISAPI/System/IO/outputs/{int(acao['saida'])}/trigger", cred["username"], cred["password"], corpo)
    return cod == 200, f"saída {acao['saida']} {estado}: HTTP {cod}" + ("" if cod == 200 else f" {txt[:120]}")


def _desligar_depois(tenant: str, acao: Dict[str, Any], regra_id: str = "", alerta_id: str = "") -> None:
    """Sirene ligada para sempre e pior que nao tocar: tenta 3 vezes e, se nao
    conseguir, deixa a falha no historico da regra (nao so no log)."""
    token = set_current_tenant_slug(tenant)
    try:
        msg = ""
        for tentativa in range(3):
            try:
                ok, msg = _saida_estado(tenant, acao, "low")
                if ok:
                    return
            except Exception as exc:
                msg = str(exc)
            if tentativa < 2:
                time.sleep(ESPERA_DESLIGAR_S)
        logger.error("automacao: NAO desligou a saida de %s: %s", acao.get("ip"), msg)
        if regra_id:
            automacao_store.registrar_execucao(regra_id, alerta_id, "valer", acao, False, f"não desligou a saída: {msg}")
    finally:
        reset_current_tenant_slug(token)


def executar_acao(tenant: str, acao: Dict[str, Any], modo: str,
                  agendar: Callable[[float, Callable, tuple], Any] | None = None,
                  regra_id: str = "", alerta_id: str = "") -> Tuple[bool, str]:
    if acao.get("tipo") == "saida":
        descr = f"ligar saída {acao.get('saida')} de {acao.get('nome')} por {acao.get('segundos')} s"
    else:
        descr = f"levar {acao.get('nome')} ao preset {acao.get('preset')}"
    if modo != "valer":
        return True, f"simulado: {descr}"
    try:
        if acao.get("tipo") == "saida":
            ok, msg = _saida_estado(tenant, acao, "high")
            if ok:
                (agendar or _timer)(float(acao["segundos"]), _desligar_depois, (tenant, acao, regra_id, alerta_id))
            return ok, msg
        base, cred = _alvo(acao)
        voltar = int(acao.get("voltar_s") or 0)
        pos = None
        if voltar:
            try:
                pos = _posicao(base, cred)
            except Exception as exc:     # nao deixa de apontar para o alarme por causa disso
                logger.warning("automacao: sem posicao de %s, nao vai voltar: %s", acao.get("ip"), exc)
        cod, txt = _put(f"{base}/ISAPI/PTZCtrl/channels/1/presets/{int(acao['preset'])}/goto", cred["username"], cred["password"])
        if cod == 200 and pos:
            (agendar or _timer)(float(voltar), _voltar_speed, (tenant, acao, pos))
        extra = "" if cod != 200 else (f", volta em {voltar} s" if pos else ", fica no preset")
        return cod == 200, f"preset {acao['preset']}: HTTP {cod}{extra}" + ("" if cod == 200 else f" {txt[:120]}")
    except Exception as exc:
        return False, f"{descr}: {exc}"[:300]


def _timer(segundos: float, fn: Callable, args: tuple) -> None:
    t = threading.Timer(segundos, fn, args=args)
    t.daemon = True
    t.start()


def _dentro_do_intervalo(regra: Dict[str, Any]) -> bool:
    ultima = automacao_store.ultima_execucao(regra["id"])
    if not ultima:
        return False
    try:
        idade = (datetime.now(timezone.utc) - datetime.strptime(ultima, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
    except ValueError:
        return False
    return idade < int(regra.get("intervalo_s") or 120)


def rodar_regra(tenant: str, regra: Dict[str, Any], alerta_id: str = "", so_simular: bool = False) -> None:
    modo = "simular" if so_simular else regra["modo"]
    for acao in regra["acoes"]:
        ok, msg = executar_acao(tenant, acao, modo, regra_id=regra["id"], alerta_id=alerta_id)
        automacao_store.registrar_execucao(regra["id"], alerta_id, modo, acao, ok, msg)
        if not ok:
            logger.warning("automacao %s (%s): %s", regra.get("nome"), tenant, msg)


def disparar(tenant: str, camera_id: str, alerta_id: str, so_simular: bool = False) -> int:
    """Roda as automacoes da camera. Devolve quantas regras rodaram.
    so_simular: nenhuma aciona equipamento, nem as que estao em Valendo."""
    token = set_current_tenant_slug(tenant)
    try:
        rodadas = 0
        for regra in automacao_store.regras_da_camera(camera_id):
            if _dentro_do_intervalo(regra):
                continue
            rodar_regra(tenant, regra, alerta_id, so_simular)
            rodadas += 1
        return rodadas
    except Exception:
        logger.exception("automacao: falha ao disparar (%s, alerta %s)", tenant, alerta_id)
        return 0
    finally:
        reset_current_tenant_slug(token)


def disparar_em_thread(tenant: str, camera_id: str, alerta_id: str, so_simular: bool = False) -> None:
    threading.Thread(target=disparar, args=(tenant, camera_id, alerta_id, so_simular), daemon=True, name="automacao").start()
