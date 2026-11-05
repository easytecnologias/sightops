"""R1: cliente A nao alcanca a rede do cliente B pelo IP virtual (vnat), nem a
API aponta para ela mesma (loopback, Docker, link-local), nem para IP privado
sem dono. O acesso do proprio cliente pelo vnat dele continua."""
from __future__ import annotations

import asyncio
import ipaddress

import pytest
from fastapi import HTTPException

from app.api.endpoints import maintenance as M
from app.api.endpoints import network_tools as NT
from app.api.endpoints import ws as W
from app.core import destino as D
from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import connector_routing_vnat as vnat
from app.services import connector_service as cs

_N = ipaddress.ip_network
MAPA = {
    "conn-a": [(_N("192.168.10.0/24"), _N("10.208.0.0/24"))],
    "conn-b": [(_N("192.168.10.0/24"), _N("10.208.1.0/24"))],
}
CONECTORES = [
    {"id": "conn-a", "tenant_slug": "cliente-a", "host": {"lan_networks": ["192.168.10.0/24"]}},
    {"id": "conn-b", "tenant_slug": "cliente-b", "host": {"lan_networks": ["192.168.10.0/24"]}},
]


@pytest.fixture
def rede(monkeypatch):
    monkeypatch.setattr(vnat, "_load_map", lambda: MAPA)
    monkeypatch.setattr(cs, "_load_connectors", lambda: [dict(c) for c in CONECTORES])
    monkeypatch.setattr(D, "_redes_do_container", lambda caminho="": [_N("172.30.0.0/16")])
    monkeypatch.setenv("DESTINO_REDES_BLOQUEADAS", "")
    monkeypatch.setattr(M, "_ip_belongs_to_current_tenant", lambda ip: ip == "10.50.0.7")
    token = set_current_tenant_slug("cliente-a")
    yield
    reset_current_tenant_slug(token)


def test_virtual_de_outro_cliente_recusado_e_o_proprio_liberado(rede):
    ok, motivo = D.destino_permitido("cliente-a", "10.208.1.5")
    assert not ok and "outro cliente" in motivo
    assert D.destino_permitido("cliente-a", "10.208.0.5") == (True, "")
    assert D.destino_permitido("cliente-b", "10.208.1.5") == (True, "")


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "0.0.0.0", "240.0.0.1",
                                "172.30.0.3", "::1", "localhost"])
def test_destinos_internos_sempre_recusados(rede, ip):
    assert D.destino_permitido("cliente-a", ip)[0] is False
    assert D.destino_permitido("", ip)[0] is False  # sem cliente tambem


def test_ip_privado_exige_dono(rede):
    assert D.destino_permitido("cliente-a", "192.168.10.40")[0] is True  # LAN do conector
    assert D.destino_permitido("cliente-a", "10.50.0.7")[0] is True       # inventario
    ok, motivo = D.destino_permitido("cliente-a", "10.99.0.1")
    assert not ok and "nao pertence" in motivo
    assert D.destino_permitido("cliente-a", "8.8.8.8")[0] is True         # internet


def test_lote_com_virtual_de_outro_cliente_da_403(rede):
    with pytest.raises(HTTPException) as exc:
        M._conferir_destinos([("10.208.0.9", ""), ("10.208.1.9", "")])
    assert exc.value.status_code == 403 and "10.208.1.9" in str(exc.value.detail)
    M._conferir_destinos([("10.208.0.9", ""), ("192.168.10.9", "conn-a")])  # o proprio passa


def test_ferramenta_de_rede_nao_conecta_no_virtual_de_outro_cliente(rede, monkeypatch):
    conectados = []

    async def _tcp(host, port, timeout):
        conectados.append(host)
        return {"host": host, "port": port, "open": False}

    monkeypatch.setattr(NT, "_tcp_check_safe", _tcp)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(NT.api_network_tools_run({"test": "tcp", "targets": "10.208.1.5", "ports": "80"}))
    assert exc.value.status_code == 403
    assert conectados == []
    res = asyncio.run(NT.api_network_tools_run({"test": "tcp", "targets": "10.208.1.5,10.208.0.5", "ports": "80"}))
    assert conectados == ["10.208.0.5"] and "10.208.1.5" in res["recusados"]


class _Ws:
    def __init__(self, fica_aberto=False):
        self.enviados = []
        self.fica_aberto = fica_aberto  # desconectar cancelaria a varredura

    async def send_text(self, texto):
        self.enviados.append(texto)

    async def receive_text(self):
        if self.fica_aberto:
            await asyncio.Event().wait()
        raise W.WebSocketDisconnect()


def _sessao(monkeypatch, primeiro):
    async def _aceita(ws, *, min_role="viewer"):
        return True, {"effective_tenant_slug": "cliente-a"}, primeiro

    monkeypatch.setattr(W, "_accept_ws_session", _aceita)


def test_ws_portscan_nao_conecta_no_virtual_de_outro_cliente(rede, monkeypatch):
    conectados = []

    async def _abre(host, port):
        conectados.append(host)
        raise OSError("sem rota")

    monkeypatch.setattr(W.asyncio, "open_connection", _abre)
    _sessao(monkeypatch, {"targets": "10.208.1.5 10.208.0.5", "ports": "80", "fast_discovery": False})
    ws = _Ws(fica_aberto=True)
    asyncio.run(W.ws_portscan(ws))
    assert conectados == ["10.208.0.5"]
    assert any("10.208.1.5" in t and "recusado" in t for t in ws.enviados)


def test_ws_snapshot_recusa_virtual_de_outro_cliente(rede, monkeypatch):
    capturas = []
    monkeypatch.setattr(W, "get_snapshot", lambda *a: capturas.append(a))
    _sessao(monkeypatch, {"ip": "10.208.1.5", "usuario": "admin", "senha": "x"})
    ws = _Ws()
    asyncio.run(W.ws_snapshot(ws))
    assert capturas == []
    assert any("outro cliente" in t for t in ws.enviados)


def test_rotas_do_container_viram_redes_bloqueadas(tmp_path):
    arq = tmp_path / "route"
    arq.write_text(
        "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
        "eth0\t00000000\t010012AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
        "eth0\t000012AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n",
        encoding="ascii")
    redes = {str(r) for r in D._redes_do_container(str(arq))}
    assert redes == {"172.18.0.0/16", "172.18.0.1/32"}
