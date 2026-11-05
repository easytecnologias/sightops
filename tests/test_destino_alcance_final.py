"""R1, 3a rodada: o IP que a guarda aprova e o IP em que a rota conecta.

Em producao o host roteia 10.0.0.0/23 pelo wg-sightops, e ha conectores
ISOLADOS de clientes diferentes com essa LAN real: conectar no IP real nao da
"No route", cai no conector de outro cliente. Entao IP real de LAN de conector
isolado nao e destino de conexao (so o virtual), e cada rota conecta pela mesma
resolucao de conector que a guarda conferiu."""
from __future__ import annotations

import ipaddress
from datetime import datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.endpoints import cameras as C
from app.api.endpoints import deployments as DP
from app.api.endpoints import maintenance as M
from app.api.endpoints import nvr as NV
from app.api.endpoints import playback as PB
from app.core import destino as D
from app.core import tenant_context as TC
from app.services import connector_routing_vnat as vnat
from app.services import connector_service as cs
from app.services import nvr_ai_service as NA
from app.services import nvr_search_service as NS
from app.services import switch_service as SS
from test_destino_permitido import CONECTORES, MAPA, rede  # noqa: F401  (fixture)

_N = ipaddress.ip_network


@pytest.fixture
def parque(rede, monkeypatch):
    """conn-a/conn-b isolados (192.168.10.0/24); faixa grande de A isolada (/19);
    conn-d isolado de B em 10.0.0.0/24 e conn-c de A SEM mapa na mesma LAN
    (rede direta de A); conn-x de B sem mapa."""
    mapa = dict(MAPA)
    mapa["conn-a"] = MAPA["conn-a"] + [(_N("172.16.0.0/19"), _N("10.208.32.0/19")),
                                       (_N("10.70.0.0/24"), _N("10.208.70.0/24"))]
    mapa["conn-d"] = [(_N("10.0.0.0/24"), _N("10.208.2.0/24"))]
    linhas = [dict(c) for c in CONECTORES] + [
        {"id": "conn-c", "tenant_slug": "cliente-a", "host": {"lan_networks": ["10.0.0.0/24", "10.70.0.0/24"]}},
        {"id": "conn-d", "tenant_slug": "cliente-b", "host": {"lan_networks": ["10.0.0.0/24"]}},
        {"id": "conn-x", "tenant_slug": "cliente-b", "host": {"lan_networks": ["10.60.0.0/24"]}},
    ]
    monkeypatch.setattr(vnat, "_load_map", lambda: mapa)
    monkeypatch.setattr(cs, "_load_connectors", lambda: [dict(c) for c in linhas])
    monkeypatch.setattr(vnat, "_dono_cache", {})
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip, hint="": {})
    monkeypatch.setattr(NV, "_recorder_connector_for_host", lambda ip: "")


# ------------------------------------------------------------------ destino
def test_ip_real_de_lan_isolada_nao_e_destino_de_conexao(parque):
    ok, motivo = D.destino_permitido("cliente-a", "192.168.10.9")
    assert not ok and "use o IP virtual" in motivo
    assert D.destino_permitido("cliente-a", "10.208.0.9") == (True, "")
    # LAN do conector SEM mapa do proprio cliente segue (rede direta dele)...
    assert D.destino_permitido("cliente-a", "10.70.0.5") == (True, "")
    # ...menos a que coincide com LAN real de conector isolado de OUTRO cliente
    ok, motivo = D.destino_permitido("cliente-a", "10.0.0.5")
    assert not ok and "use o IP virtual" in motivo
    ok, motivo = D.destino_permitido("cliente-b", "10.0.0.5")
    assert not ok and "use o IP virtual" in motivo
    # mesma regra sem exigir dono (OLT cadastrada, ARP da ativacao)
    assert D.destino_permitido("cliente-b", "10.0.0.5", exigir_dono=False)[0] is False


def test_varredura_grande_da_lan_real_isolada_recusada(parque):
    assert D.varredura_recusada("cliente-a", "172.16.0.0/19") != ""  # bloco grande (sem olhar IP a IP)
    assert D.varredura_recusada("cliente-a", "10.208.32.0/19") == ""


# --------------------------------------------------------------------- vnat
def test_conector_de_outro_cliente_sem_mapa_nao_devolve_ip_real(parque):
    assert vnat.virtual_ip_for("conn-x", "10.60.0.5") == vnat.IP_BLOQUEADO
    assert vnat.virtual_ip_for("conn-c", "10.0.0.5") == "10.0.0.5"     # dele, sem mapa
    assert vnat.virtual_ip_for("nao-existe", "10.60.0.5") == "10.60.0.5"  # inexistente: como antes


# ------------------------------------------------------- mesma resolucao
def test_implantacao_ip_porta_vai_pelo_virtual(parque):
    assert DP._reach_deploy_host("192.168.10.9:8080", "conn-a") == "10.208.0.9:8080"
    assert DP._reach_deploy_host("192.168.10.9", "conn-a") == "10.208.0.9"


def test_implantacao_sem_conector_usa_a_resolucao_da_guarda(parque, monkeypatch):
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip, hint="": {"remote_connector_id": "conn-a"})
    assert DP._reach_deploy_host("192.168.10.9", "") == "10.208.0.9"


def test_rota_de_gravador_conecta_pelo_conector_que_a_guarda_conferiu(parque, monkeypatch):
    app = FastAPI()

    @app.middleware("http")
    async def _tenant(request, call_next):
        token = TC.set_current_tenant_slug("cliente-a")
        try:
            return await call_next(request)
        finally:
            TC.reset_current_tenant_slug(token)

    app.include_router(NV.router)
    bases = []
    monkeypatch.setattr(NV, "_probe_nvr_stack", lambda base, *a: bases.append(base) or {"ok": False})
    tc = TestClient(app, raise_server_exceptions=False)
    r = tc.post("/api/nvr/reboot", json={"ip": "192.168.10.9", "connector_id": "conn-a", "password": "x"})
    assert r.status_code == 401
    assert bases == ["http://10.208.0.9"]


def test_playback_e_snapshot_baixam_pelo_ip_conferido(parque, monkeypatch):
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip, hint="": {"remote_connector_id": "conn-a"})
    assert PB._reach_playback_host("192.168.10.9", "") == "10.208.0.9"
    alvos = []
    monkeypatch.setattr(C, "_ip_in_inventory", lambda ip, cid="": True)
    monkeypatch.setattr(C, "resolve_camera_password", lambda ip, u, p, c="": ("admin", "x"))
    monkeypatch.setattr(C, "get_snapshot", lambda ip, *a, **k: alvos.append(ip) or "")
    try:
        C.api_cameras_snapshot_capture(C.SnapshotCaptureRequest(ip="192.168.10.9"))
    except HTTPException:
        pass
    assert alvos == ["10.208.0.9"]


def test_ia_busca_pelo_ip_virtual_do_gravador(parque, monkeypatch):
    monkeypatch.setattr(NV, "_recorder_connector_for_host", lambda ip: "conn-a" if ip == "192.168.10.9" else "")
    hosts = []
    monkeypatch.setattr(NA, "dahua_media_find_segments", lambda **k: hosts.append(k["host"]) or {"segments": []})
    NA.query_recording_segments({"host": "192.168.10.9", "password": "x", "channel": 1,
                                 "start_time": "2026-11-01 10:00:00", "end_time": "2026-11-01 10:05:00"})
    assert hosts == ["10.208.0.9"]
    monkeypatch.setattr(NS, "query_recording_segments", lambda p: {"record_segments": [1]})
    monkeypatch.setattr(NS, "download_clip_mp4", lambda **k: hosts.append(k["host"]) or (_ for _ in ()).throw(OSError("x")))
    t0 = datetime(2026, 11, 1, 10, 0, 0)
    NS._search_one_camera(target={"host": "192.168.10.9", "channel": 1}, user="a", password="b",
                          start_dt=t0, end_dt=t0, query="q")
    assert hosts[-1] == "10.208.0.9"
    # vizinho do cadastro com IP real de LAN isolada e sem conector: nao baixa
    hit, motivo = NS._search_one_camera(target={"host": "192.168.10.20", "channel": 1}, user="a", password="b",
                                        start_dt=t0, end_dt=t0, query="q")
    assert hit is None and "falha ao baixar" in motivo
    assert hosts[-1] == "10.208.0.9"


def test_switch_conecta_pelo_virtual_e_recusa_destino_alheio(parque, monkeypatch):
    monkeypatch.setattr(M, "_switch_connector_for_ip", lambda ip: "conn-a" if ip == "192.168.10.9" else "")
    assert SS._host_alcancavel("", "192.168.10.9") == "10.208.0.9"
    assert SS._host_alcancavel("conn-a", "192.168.10.9") == "10.208.0.9"
    with pytest.raises(HTTPException) as exc:
        SS._host_alcancavel("", "10.208.1.5")
    assert exc.value.status_code == 403


def test_inspecao_de_switch_conecta_pelo_virtual(parque, monkeypatch):
    from app.api.endpoints import switch as SW
    hosts = []
    monkeypatch.setattr(SW, "collect_hikvision_switch_snapshot", lambda **k: hosts.append(k["host"]) or {})
    monkeypatch.setattr(SW, "collect_switch_snapshot", lambda **k: hosts.append(k["host"]) or {})
    corpo = {"host": "192.168.10.9", "connector_id": "conn-a", "user": "a", "pass": "b"}
    assert SW.inspect_hikvision_switch(corpo)["ok"]
    assert SW.inspect_intelbras_switch(corpo)["ok"]
    assert hosts == ["10.208.0.9", "10.208.0.9"]
