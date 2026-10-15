"""Gaveta Controladora: leitura do estado, acertar hora, NTP, fechar porta e
reiniciar. Leitor falso (respostas no formato da HTTP API Intelbras V3.59):
nenhum equipamento de verdade."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.services import access_control_controladora as C


class _Resp:
    def __init__(self, texto, status=200):
        self.text, self.status_code = texto, status


class LeitorFalso:
    """Responde como uma ASI6213S-W com o relogio zerado."""

    def __init__(self, hora="2000-01-01 03:12:00", falhar=()):
        self.chamadas = []
        self.hora = hora
        self.falhar = set(falhar)

    def __call__(self, device, path, params):
        self.chamadas.append((path, dict(params)))
        acao = params.get("action")
        if acao in self.falhar:
            raise HTTPException(status_code=502, detail="timeout")
        if acao == "getDeviceType":
            return _Resp("type=ASI6213S-W")
        if acao == "getSoftwareVersion":
            return _Resp("version=1.000.0000002.0.R,build:2024-03-12")
        if acao == "getSerialNo":
            return _Resp("sn=8L0A1B2C3D4E5")
        if acao == "getCurrentTime":
            return _Resp(f"result={self.hora}")
        if acao == "getConfig":
            return _Resp("table.NTP.Address=clock.isc.org\ntable.NTP.Enable=false\ntable.NTP.TimeZone=9\ntable.NTP.TimeZoneDesc=GMT")
        if acao == "getDoorStatus":
            return _Resp("Info.status=Close")
        return _Resp("OK")


AGORA = datetime(2026, 10, 15, 14, 21, 48, tzinfo=timezone.utc)   # 11:21:48 em Brasilia


@pytest.fixture(autouse=True)
def leitor_do_cliente(monkeypatch):
    monkeypatch.setattr(C, "_leitor", lambda did: {"id": did, "name": "ENTRADA", "vendor": "intelbras"})


def test_diagnostico_mostra_relogio_errado_ntp_e_porta():
    get = LeitorFalso()
    r = C.diagnostico("d1", get=get, agora=AGORA)
    assert r["modelo"] == "ASI6213S-W" and r["serie"] == "8L0A1B2C3D4E5"
    assert r["hora_certa"] == "2026-10-15 11:21:48"
    assert r["hora_ok"] is False and r["diferenca_segundos"] < -10 * 365 * 86400
    assert r["ntp"] == {"ativo": False, "servidor": "clock.isc.org", "fuso": "9", "fuso_desc": "GMT", "fuso_ok": False}
    assert r["porta"] == "fechada"


def test_diagnostico_aguenta_comando_que_o_firmware_nao_tem():
    r = C.diagnostico("d1", get=LeitorFalso(hora="2026-10-15 11:22:30", falhar={"getConfig"}), agora=AGORA)
    assert r["hora_ok"] is True and "ntp" in r["erros"] and "ntp" not in r


def test_leitor_mudo_vira_erro_claro():
    falha = {"getDeviceType", "getSoftwareVersion", "getSerialNo", "getCurrentTime", "getConfig", "getDoorStatus"}
    with pytest.raises(HTTPException) as e:
        C.diagnostico("d1", get=LeitorFalso(falhar=falha), agora=AGORA)
    assert "nao respondeu" in e.value.detail


def test_acertar_hora_manda_hora_de_brasilia():
    get = LeitorFalso()
    r = C.acertar_hora("d1", "rads", get=get, agora=AGORA)
    assert r["hora"] == "2026-10-15 11:21:48"
    assert get.chamadas == [("/cgi-bin/global.cgi", {"action": "setCurrentTime", "time": "2026-10-15 11:21:48"})]


def test_ntp_liga_com_fuso_de_brasilia_e_recusa_servidor_estranho():
    get = LeitorFalso()
    C.configurar_ntp("d1", "rads", "a.ntp.br", True, get=get)
    assert get.chamadas[-1][1] == {"action": "setConfig", "NTP.Enable": "true", "NTP.Address": "a.ntp.br",
                                   "NTP.Port": "123", "NTP.TimeZone": "22"}
    with pytest.raises(HTTPException):
        C.configurar_ntp("d1", "rads", "a.ntp.br&NTP.Enable=false", True, get=get)


def test_fechar_porta_e_reiniciar():
    get = LeitorFalso()
    C.fechar_porta("d1", "rads", get=get)
    C.reiniciar("d1", "rads", get=get)
    assert get.chamadas[0] == ("/cgi-bin/accessControl.cgi", {"action": "closeDoor", "channel": 1, "UserID": "SightOps", "Type": "Remote"})
    assert get.chamadas[1] == ("/cgi-bin/magicBox.cgi", {"action": "reboot"})


def test_reiniciar_exige_admin():
    from app.core.security import ApiAuthMiddleware

    async def app_vazio(scope, receive, send):
        return None

    from app.core.settings import get_settings
    regras = ApiAuthMiddleware(app_vazio, get_settings())
    assert regras._match_role_rule("/api/access-control/painel/reiniciar-controladora/d1", "POST") == "admin"
    assert regras._match_role_rule("/api/access-control/painel/controladora/d1/hora", "POST") == "operator"
    assert regras._match_role_rule("/api/access-control/painel/controladora/d1/fechar", "POST") == "operator"
