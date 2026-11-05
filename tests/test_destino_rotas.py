"""Rotas de ping e descoberta passam pela regra unica de destino. Destino
recusado e erro por linha, nunca "offline" gravado; conector sem mapa idem."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.endpoints import cameras as C
from app.api.endpoints import tools as T
from app.services import connector_routing_vnat as vnat
from test_destino_permitido import rede  # noqa: F401  (fixture)


@pytest.fixture
def ping(rede, monkeypatch):
    pingados = []

    async def _ping(ip, timeout=2, method="auto", force=0, preferred_ports=None):
        pingados.append(ip)
        return {"ip": ip, "online": False, "method": "icmp"}

    monkeypatch.setattr(C, "ping_with_cache", _ping)
    persistidos = []
    monkeypatch.setattr(C, "_persist_camera_statuses", lambda d: persistidos.append(dict(d)) or {"camera_rows": len(d)})
    return pingados, persistidos


def _lote(itens):
    req = C.PingBatchRequest(items=[C.PingBatchItem(**i) for i in itens], persist=True, force=1)
    return asyncio.run(C.api_cameras_ping_many(req))


def test_ping_many_recusa_virtual_alheio_por_linha_sem_gravar_offline(ping):
    pingados, persistidos = ping
    res = _lote([{"ip": "10.208.1.5"}, {"ip": "127.0.0.1"}, {"ip": "10.208.0.5"}])
    assert pingados == ["10.208.0.5"]
    por_ip = {r["ip"]: r for r in res["results"]}
    assert por_ip["10.208.1.5"]["sem_rota"] and por_ip["10.208.1.5"]["error"]
    assert por_ip["127.0.0.1"]["sem_rota"]
    assert persistidos == [{"10.208.0.5": "offline"}]


def test_ping_many_conector_de_outro_cliente_nao_pinga_nem_grava(ping, monkeypatch):
    pingados, persistidos = ping
    monkeypatch.setattr(vnat, "_conector_do_cliente", lambda cid: cid == "conn-a")
    res = _lote([{"ip": "192.168.10.5", "remote_connector_id": "conn-b"}])
    assert pingados == []
    assert res["results"][0]["sem_rota"] and res["results"][0]["error"]
    assert persistidos == [{}]


def test_ping_many_conector_com_mapa_grava_offline_de_verdade(ping):
    pingados, persistidos = ping
    res = _lote([{"ip": "192.168.10.5", "remote_connector_id": "conn-a"}])
    assert pingados == ["10.208.0.5"]
    assert not res["results"][0].get("sem_rota")
    assert persistidos == [{"192.168.10.5": "offline"}]


def test_ping_unico_da_403_no_destino_recusado(ping):
    pingados, _ = ping
    for alvo in ("10.208.1.5", "10.208.1.5:81"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(C.api_cameras_ping(ip=alvo))
        assert exc.value.status_code == 403
    assert pingados == []


def test_ping_unico_conector_de_outro_cliente_da_403(ping, monkeypatch):
    pingados, _ = ping
    monkeypatch.setattr(vnat, "_conector_do_cliente", lambda cid: cid == "conn-a")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(C.api_cameras_ping(ip="192.168.10.5", remote_connector_id="conn-b"))
    assert exc.value.status_code == 403
    assert pingados == []


def test_scan_ip_da_403_sem_conectar(rede, monkeypatch):
    conectou = []
    monkeypatch.setattr(T, "_quick_scan_open_ports", lambda *a: conectou.append(a) or [])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(T.api_tools_scan_ip({"ip": "10.208.1.5", "ports": "80"}))
    assert exc.value.status_code == 403
    assert conectou == []


def test_descoberta_tira_recusados_e_nao_conecta_neles(rede, monkeypatch):
    conectados = []

    async def _abre(host, port):
        conectados.append(host)
        raise OSError("sem rota")

    monkeypatch.setattr(T.asyncio, "open_connection", _abre)
    res = asyncio.run(T.api_discovery_run({"targets": "10.208.1.5,10.208.0.5", "ports": "80"}))
    assert conectados == ["10.208.0.5"]
    assert "10.208.1.5" in res["recusados"]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(T.api_discovery_run({"targets": "10.208.1.5", "ports": "80"}))
    assert exc.value.status_code == 403
