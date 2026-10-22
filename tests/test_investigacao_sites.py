"""Investigacao: usuario restrito a sites so ve e abre gravador dos sites dele."""
import pytest
from fastapi import HTTPException

from app.api.endpoints import ia, recorder_driver
from app.core import permissions
from app.services import nvr_ai_service

LINHAS = [
    {"host": "10.0.0.1", "channel": 1, "site": "ESCOLA MEDEA"},
    {"host": "10.0.0.2", "channel": 1, "site": "PORTO REAL DO COLEGIO"},
    {"host": "10.0.0.3", "channel": 1, "site": "", "local": "ESCOLA MEDEA"},
]


@pytest.fixture
def restrito(monkeypatch):
    monkeypatch.setattr(nvr_ai_service, "_read_nvr_inventory", lambda: [dict(r) for r in LINHAS])
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: ["Escola Medea"])


def test_lista_so_sites_do_usuario(restrito):
    data = ia.api_ia_nvr_targets()
    assert sorted(t["host"] for t in data["targets"]) == ["10.0.0.1", "10.0.0.3"]
    assert data["count"] == 2


def test_abrir_gravador_de_outro_site_da_403(restrito):
    assert recorder_driver._host_liberado("10.0.0.1")
    assert not recorder_driver._host_liberado("10.0.0.2")
    assert not recorder_driver._host_liberado("10.9.9.9")
    with pytest.raises(HTTPException) as e:
        recorder_driver._abrir("10.0.0.2", 80)
    assert e.value.status_code == 403


def test_sem_restricao_ve_tudo(monkeypatch):
    monkeypatch.setattr(nvr_ai_service, "_read_nvr_inventory", lambda: [dict(r) for r in LINHAS])
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: None)
    assert ia.api_ia_nvr_targets()["count"] == 3
    assert recorder_driver._host_liberado("10.9.9.9")


def test_nome_vem_de_cameras_ip_quando_existe(monkeypatch):
    """O NVR so tem o serial de fabrica; o nome cuidado fica em Cameras IP."""
    from app.services import inventory_json

    nvr = [
        {"host": "10.0.0.1", "channel": 1, "site": "PORTO", "title": "7KOM1407696I2", "camera_ip": "10.45.0.101"},
        {"host": "10.0.0.1", "channel": 2, "site": "PORTO", "title": "2 - Praca", "camera_ip": "10.45.0.102"},
        {"host": "10.0.0.1", "channel": 3, "site": "PORTO", "title": "SERIAL3", "camera_ip": "10.45.0.103"},
        {"host": "10.0.0.2", "channel": 1, "site": "PORTO", "title": "X1", "camera_ip": "10.9.9.9"},
        {"host": "10.0.0.3", "channel": 1, "site": "PORTO", "title": "X2", "camera_ip": "10.9.9.9"},
        {"host": "10.0.0.4", "channel": 1, "site": "OUTRO", "title": "Y1", "camera_ip": "10.45.0.101"},
    ]
    cams = {"switch": [
        {"ip": "10.45.0.101", "titulo": "1 - ENTRADA CIDADE", "site": "PORTO"},
        {"ip": "10.45.0.102", "titulo": "2 - PRACA", "local": "PORTO"},
        {"ip": "10.9.9.9", "titulo": "AMBIGUO", "site": "PORTO"},
    ]}
    monkeypatch.setattr(nvr_ai_service, "_read_nvr_inventory", lambda: [dict(r) for r in nvr])
    monkeypatch.setattr(inventory_json, "load_inventory_json", lambda site="", mode="olt": cams.get(mode, []))
    t = {(x["host"], x["channel"]): x for x in nvr_ai_service.list_nvr_targets()["targets"]}
    assert t[("10.0.0.1", 1)]["title"] == "1 - ENTRADA CIDADE"
    assert t[("10.0.0.1", 1)]["nvr_title"] == "7KOM1407696I2"
    assert t[("10.0.0.1", 2)]["title"] == "2 - PRACA"
    assert t[("10.0.0.1", 3)]["title"] == "SERIAL3"          # sem cadastro: fica o do NVR
    assert t[("10.0.0.2", 1)]["title"] == "X1"               # IP em 2 canais: ambiguo
    assert t[("10.0.0.4", 1)]["title"] == "Y1"               # mesmo IP, outro site
