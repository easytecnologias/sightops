"""Rotas que abrem conexao com equipamento passam pela regra unica de destino
ANTES do handler; gravador/OLT do proprio cliente continuam."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import cameras as C
from app.api.endpoints import deployments as DP
from app.api.endpoints import dvr as DV
from app.api.endpoints import maintenance as M
from app.api.endpoints import network_map as NM
from app.api.endpoints import nvr as NV
from app.api.endpoints import olt as O
from app.api.endpoints import playback as PB
from app.api.endpoints import switch as SW
from app.api.endpoints import tools as T
from app.core import tenant_context as TC
from app.services import olt_registry
from app.services import recorder_xray as RX
from test_destino_permitido import rede  # noqa: F401  (fixture)


@pytest.fixture
def cliente(rede, monkeypatch):
    """App de teste com os routers; o tenant entra por middleware (o teste nao
    passa pelo login). O handler nunca pode rodar quando o destino e recusado."""
    rodou = []
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request, call_next):
        token = TC.set_current_tenant_slug("cliente-a")
        try:
            return await call_next(request)
        finally:
            TC.reset_current_tenant_slug(token)

    for mod in (NV, DV, SW, DP):
        app.include_router(mod.router)
    monkeypatch.setattr(NV, "_recorder_connector_for_host", lambda ip: "")
    for mod, nomes in ((NV, ("_base",)), (DV, ("_base",))):
        for nome in nomes:
            monkeypatch.setattr(mod, nome, lambda *a, **k: rodou.append(a) or (_ for _ in ()).throw(RuntimeError("rodou")))
    return TestClient(app, raise_server_exceptions=False), rodou


@pytest.mark.parametrize("caminho", ["/api/nvr/reboot", "/api/dvr/reboot", "/api/nvr/ntp", "/api/dvr/change_ip",
                                     "/api/nvr/channel/change_ip", "/api/nvr/scan", "/api/dvr/scan",
                                     "/api/nvr/network", "/api/nvr/channel/rename", "/api/dvr/snapshot/update"])
def test_gravador_de_outro_cliente_da_403_sem_conectar(cliente, caminho):
    tc, rodou = cliente
    r = tc.post(caminho, json={"ip": "10.208.1.5", "user": "a", "password": "b", "address": "x", "new_ip": "1.1.1.1"})
    assert r.status_code == 403
    assert rodou == []


def test_get_de_rede_do_gravador_tambem(cliente):
    tc, rodou = cliente
    assert tc.get("/api/dvr/network", params={"ip": "127.0.0.1"}).status_code == 403
    assert rodou == []


def test_gravador_do_proprio_cliente_passa_pelo_guard(cliente):
    tc, rodou = cliente
    tc.post("/api/nvr/reboot", json={"ip": "192.168.10.9", "connector_id": "conn-a", "user": "a", "password": "b"})
    assert len(rodou) == 1


@pytest.mark.parametrize("caminho,corpo", [
    ("/api/switch/intelbras/inspect", {"host": "10.208.1.5", "user": "a", "pass": "b"}),
    ("/api/switch/hikvision/inspect", {"ip": "169.254.169.254", "user": "a", "pass": "b"}),
    ("/api/switch/collect-macs", {"switch_ip": "10.208.1.5", "user": "a", "password": "b"}),
    ("/api/deployments/apply-camera-ip", {"ip": "10.208.1.5", "new_ip": "1.1.1.1"}),
    ("/api/deployments/camera-xray", {"ip": "10.208.1.5"}),
    ("/api/deployments/recorder-login", {"recorder_type": "nvr", "recorder_host": "10.208.1.5"}),
    ("/api/deployments/recorder-xray", {"host": "10.208.1.5:8080"}),
])
def test_switch_e_implantacao(cliente, caminho, corpo):
    tc, _ = cliente
    assert tc.post(caminho, json=corpo).status_code == 403


def test_conferir_alcance_sem_conector_agora_confere(rede):
    with pytest.raises(ValueError):
        RX.conferir_alcance("10.208.1.5", "")
    RX.conferir_alcance("192.168.10.9", "")


def test_playback_recusa_antes_do_download(rede, monkeypatch):
    monkeypatch.setattr(PB, "_conector_do_gravador", lambda h, c="": "")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        PB._conferir_gravador("10.208.1.5", "")
    assert exc.value.status_code == 403


def test_snapshot_capture_e_caminho_de_rede(rede, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(C, "_ip_in_inventory", lambda ip, cid="": True)
    monkeypatch.setattr(C, "resolve_camera_password", lambda ip, u, p, c="": ("admin", "x"))
    monkeypatch.setattr(C, "get_snapshot", lambda *a, **k: pytest.fail("conectou"))
    with pytest.raises(HTTPException) as exc:
        C.api_cameras_snapshot_capture(C.SnapshotCaptureRequest(ip="10.99.0.1"))
    assert exc.value.status_code == 403
    monkeypatch.setattr(NM.connector_service, "conector_do_site_liberado", lambda u, c: True)
    monkeypatch.setattr(M, "alvo_permitido", lambda *a, **k: (True, ""))

    class _Req:
        state = type("S", (), {"current_user": None})()

    with pytest.raises(HTTPException) as exc:
        NM.api_network_path(_Req(), connector_id="conn-a", ip="10.208.1.5")
    assert exc.value.status_code == 403


def test_zabbix_groups_recusa_url_interna_digitada(rede, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(M, "_load_settings", lambda: {"zabbix_ip_sync": {"url": "http://zbx.exemplo/api_jsonrpc.php"}})
    with pytest.raises(HTTPException) as exc:
        M.api_scripts_zabbix_groups(url="http://169.254.169.254/latest", user="a", password="b")
    assert exc.value.status_code == 403


def test_relay_telegram_recusa_rede_interna(rede):
    import asyncio
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        asyncio.run(T.api_telegram_relay_send({"token": "t", "chat_id": "1",
                                               "snapshot_url": "http://127.0.0.1:8000/x.jpg"}))
    assert exc.value.status_code == 403


def test_olt_cadastrada_em_faixa_alheia_da_403_e_a_propria_passa(rede, monkeypatch):
    from fastapi import HTTPException
    from app.models.requests import OltOnuSignalRequest
    host = {"v": "10.208.1.7"}
    monkeypatch.setattr(olt_registry, "resolve_credentials", lambda i: {
        "id": 7, "host": host["v"], "username": "u", "password": "p", "connector_id": "",
        "active": True, "name": "OLT", "site": "", "model": "", "vendor": ""})
    with pytest.raises(HTTPException) as exc:
        O._registered_request(OltOnuSignalRequest(olt_id=7))
    assert exc.value.status_code == 403
    host["v"] = "10.77.0.2"  # fora das LANs coletadas: OLT cadastrada nao exige dono
    assert O._registered_request(OltOnuSignalRequest(olt_id=7)).olt_ip == "10.77.0.2"
