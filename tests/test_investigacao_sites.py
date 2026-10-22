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
