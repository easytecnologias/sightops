"""R1, 2a rodada: rotas de implantacao, IA e ativacao que ainda alcancavam
equipamento pelo IP do pedido sem a regra unica de destino. O gravador/camera
do proprio cliente (LAN ou faixa virtual do conector dele) continua passando."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.endpoints import camera_activation as CA
from app.api.endpoints import deployments as DP
from app.api.endpoints import ia as IA
from app.core import tenant_context as TC
from test_destino_permitido import rede  # noqa: F401  (fixture)
from test_guarda_destino import cliente  # noqa: F401  (fixture)


# --------------------------------------------------------------- implantacao
@pytest.fixture
def gravador(cliente, monkeypatch):
    tc, _ = cliente
    tocou = []
    monkeypatch.setattr(DP, "_credencial_gravador", lambda p: ("admin", "x"))
    monkeypatch.setattr(DP, "_fetch_recorder_live_channels",
                        lambda base, *a, **k: tocou.append(base) or ({}, False))
    monkeypatch.setattr(DP, "_recorder_family", lambda base, *a: tocou.append(base) or "intelbras")
    import app.api.endpoints.recorder_driver as RD
    monkeypatch.setattr(RD, "gravador_liberado", lambda host, cid="": cid)
    import app.services.live_stream_service as LS
    monkeypatch.setattr(LS, "register_recorder_stream", lambda **k: tocou.append(k["host"]) or "rec_x")
    return tc, tocou


_CORPO = {"recorder_type": "nvr", "recorder_channel": 1, "canal": 1, "recorder_camera_ip": "192.168.10.50",
          "camera_password": "c", "recorder_title": "t"}


@pytest.mark.parametrize("caminho", ["/api/deployments/recorder-channels", "/api/deployments/recorder-add-camera",
                                     "/api/deployments/recorder-remove-camera", "/api/deployments/recorder-live-stream"])
@pytest.mark.parametrize("host", ["10.208.1.5", "127.0.0.1", "10.99.0.1"])
def test_gravador_alheio_ou_interno_da_403_sem_conectar(gravador, caminho, host):
    tc, tocou = gravador
    r = tc.post(caminho, json={**_CORPO, "recorder_host": host})
    assert r.status_code == 403
    assert tocou == []


def test_gravador_do_proprio_cliente_passa(gravador):
    tc, tocou = gravador
    r = tc.post("/api/deployments/recorder-channels",
                json={**_CORPO, "recorder_host": "192.168.10.9", "connector_id": "conn-a"})
    assert r.status_code == 200
    assert tocou == ["http://10.208.0.9"]
    r = tc.post("/api/deployments/recorder-live-stream",
                json={**_CORPO, "recorder_host": "10.208.0.9"})
    assert r.status_code == 200


# ----------------------------------------------------------------------- IA
@pytest.fixture
def ia(rede, monkeypatch):
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request, call_next):
        token = TC.set_current_tenant_slug("cliente-a")
        try:
            return await call_next(request)
        finally:
            TC.reset_current_tenant_slug(token)

    app.include_router(IA.router)
    from app.api.endpoints import nvr as NV
    monkeypatch.setattr(NV, "_recorder_connector_for_host", lambda ip: "")
    monkeypatch.setattr(IA, "_exigir_host_liberado", lambda host: None)  # gravador fora do cadastro passa nela
    monkeypatch.setattr(IA, "_resolve_ia_password", lambda h, u, p: ("admin", "x"))
    tocou = []
    monkeypatch.setattr(IA, "query_recording_segments", lambda p: tocou.append(p["host"]) or {"ok": True})
    monkeypatch.setattr(IA._SEARCH_EXECUTOR, "submit", lambda *a, **k: tocou.append("job"))
    return TestClient(app, raise_server_exceptions=False), tocou


_IA = {"channel": 1, "start_time": "2026-11-01 10:00:00", "end_time": "2026-11-01 10:05:00", "query": "carro"}


@pytest.mark.parametrize("caminho", ["/api/ia/nvr/recordings", "/api/ia/nvr/search/jobs"])
def test_ia_nao_busca_em_gravador_de_outro_cliente(ia, caminho):
    tc, tocou = ia
    assert tc.post(caminho, json={**_IA, "host": "10.208.1.5"}).status_code == 403
    assert tc.post(caminho, json={**_IA, "host": "169.254.169.254"}).status_code == 403
    assert tocou == []
    assert tc.post(caminho, json={**_IA, "host": "192.168.10.9"}).status_code == 200
    assert len(tocou) == 1


# ------------------------------------------------------------------ ativacao
class _Req:
    state = type("S", (), {"current_user": None})()


@pytest.fixture
def ativacao(rede, monkeypatch):
    tocou = []
    monkeypatch.setattr(CA.hikvision, "reiniciar", lambda base, s: tocou.append(base) or {"ok": True})
    monkeypatch.setattr(CA.hikvision, "ativar", lambda base, s: tocou.append(base) or {"ok": False, "error": "x"})
    monkeypatch.setattr(CA.hikvision, "procurar", lambda restantes, macs: tocou.extend(restantes) or [])
    monkeypatch.setattr(CA.netsdk, "search_devices_isolado", lambda ips: tocou.extend(ips) or {"ok": True, "devices": []})
    monkeypatch.setattr(CA, "_acordar_ip_de_fabrica", lambda cid, ips: False)
    monkeypatch.setattr(CA, "_ips_de_fabrica_do_site", lambda cid: [])
    monkeypatch.setattr(CA, "_connector_inventory", lambda cid: {"inventory": {}})
    monkeypatch.setattr(CA, "_dados_pelos_gravadores", lambda cid: {})
    return tocou


@pytest.mark.parametrize("rota", [CA.api_activation_reboot, CA.api_activation_run])
def test_ativacao_nao_mexe_em_camera_de_outro_cliente(ativacao, rota):
    corpo = {"connector_id": "conn-a", "senha": "Senha#123",
             "targets": [{"ip": "192.168.10.7", "vendor": "hikvision"}, {"ip": "10.208.1.5", "vendor": "hikvision"}]}
    with pytest.raises(HTTPException) as exc:
        rota(corpo, _Req())
    assert exc.value.status_code == 403 and "10.208.1.5" in str(exc.value.detail)
    assert ativacao == []
    rota({**corpo, "targets": corpo["targets"][:1]}, _Req())
    assert ativacao == ["http://10.208.0.7"]


def test_varredura_manual_com_ip_alheio_da_403(ativacao):
    with pytest.raises(HTTPException) as exc:
        CA.api_activation_scan({"connector_id": "conn-a", "ips": ["192.168.10.7", "10.208.1.5"]}, _Req())
    assert exc.value.status_code == 403
    assert ativacao == []


def test_varredura_pelo_arp_pula_so_destino_alheio(ativacao, monkeypatch):
    monkeypatch.setattr(CA, "_ips_do_conector", lambda cid: ["192.168.10.7", "10.208.1.5", "127.0.0.1", "10.77.0.9"])
    CA.api_activation_scan({"connector_id": "conn-a"}, _Req())
    # o IP fora das LANs coletadas fica (nao exige dono); faixa alheia e loopback saem
    assert sorted(set(ativacao)) == ["10.208.0.7", "10.77.0.9"]
