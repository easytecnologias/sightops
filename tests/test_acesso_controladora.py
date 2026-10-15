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


def test_sincronismo_zabbix_reaproveita_a_sessao(monkeypatch):
    """Antes: user.login a cada rodada, ~6.100 sessoes novas por dia no Zabbix."""
    from app.services import zabbix_monitoring_service as Z
    chamadas = []

    def falso(url, method, params, auth=None, req_id=1):
        chamadas.append(method)
        if method == "user.login":
            return f"tok{chamadas.count('user.login')}"
        if method == "user.checkAuthentication":
            if params["sessionid"] == "tok1" and "expira" in chamadas:
                raise RuntimeError("Session terminated")
            return {"userid": "1"}
        return None

    monkeypatch.setattr(Z, "_call", falso)
    Z._SESSOES.clear()
    assert Z._sessao("u", "Admin", "x") == "tok1"
    assert Z._sessao("u", "Admin", "x") == "tok1"          # reaproveitou
    assert chamadas.count("user.login") == 1
    chamadas.append("expira")
    assert Z._sessao("u", "Admin", "x") == "tok2"          # expirou: loga de novo


def test_job_antigo_de_leitura_perde_o_conteudo_mas_nao_o_registro():
    from datetime import datetime, timedelta, timezone
    from app.services import connector_service as CS
    agora = datetime.now(timezone.utc)
    velho = (agora - timedelta(minutes=30)).isoformat()
    novo = (agora - timedelta(minutes=2)).isoformat()
    jobs = [
        {"id": "1", "type": "access_http_get", "status": "done", "finished_at": velho, "result": {"access_http": "x" * 13000}},
        {"id": "2", "type": "access_http_get", "status": "done", "finished_at": novo, "result": {"access_http": "y"}},
        {"id": "3", "type": "wireguard_diagnose", "status": "done", "finished_at": velho, "result": {"diag": "ok"}},
        {"id": "4", "type": "access_http_get", "status": "running", "picked_at": velho, "result": None},
    ]
    r = {j["id"]: j for j in CS._podar_jobs(jobs)}
    assert set(r) == {"1", "2", "3", "4"}
    assert r["1"]["result"] is None and r["1"]["result_descartado"] is True   # leitura velha: so o registro
    assert r["2"]["result"] == {"access_http": "y"}                           # recente: quem pediu ainda le
    assert r["3"]["result"] == {"diag": "ok"}                                 # diagnostico fica inteiro


def test_erro_do_leitor_nao_sai_como_502_no_controle_de_acesso():
    """Cloudflare troca 502 da origem pela pagina dele e o motivo sumia."""
    import asyncio
    from starlette.requests import Request
    import app.main as m

    def req(path):
        return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""})

    r = asyncio.run(m._erro_do_leitor_sem_502(req("/api/access-control/devices/d1/test"),
                                              HTTPException(502, "Usuario ou senha invalidos no dispositivo.")))
    assert r.status_code == 424 and b"Usuario ou senha invalidos" in r.body
    assert asyncio.run(m._erro_do_leitor_sem_502(req("/api/cameras/c1"), HTTPException(502, "x"))).status_code == 502
