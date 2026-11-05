"""IP_BLOQUEADO nao e IP valido, e conector sem mapa nao vira offline falso."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.endpoints import cameras as C
from app.services import connector_routing_vnat as vnat
from test_destino_permitido import rede  # noqa: F401  (fixture)
from test_destino_rotas import _lote, ping  # noqa: F401  (fixture)


def test_ping_many_conector_sem_mapa_nao_grava_offline_falso(ping, monkeypatch):
    """virtual_ip_for devolve o IP real quando nao ha mapa: sem_rota nunca
    disparava e a camera atras do conector virava offline."""
    pingados, persistidos = ping
    res = _lote([{"ip": "192.168.10.77", "remote_connector_id": "conn-sem-mapa"}])
    assert res["results"][0]["sem_rota"] is True
    assert persistidos == [{}]


def test_snapshot_capture_nao_tenta_ip_bloqueado(rede, monkeypatch):
    monkeypatch.setattr(vnat, "_conector_do_cliente", lambda cid: False)
    monkeypatch.setattr(C, "_ip_in_inventory", lambda ip, cid="": True)
    monkeypatch.setattr(C, "resolve_camera_password", lambda ip, u, p, c="": ("admin", "x"))
    tentou = []
    monkeypatch.setattr(C, "get_snapshot", lambda *a, **k: tentou.append(a))
    with pytest.raises(HTTPException) as exc:
        C.api_cameras_snapshot_capture(C.SnapshotCaptureRequest(ip="192.168.10.5", remote_connector_id="conn-b"))
    assert exc.value.status_code == 403
    assert tentou == []
