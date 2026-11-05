"""DNS rebinding: o nome e resolvido uma vez so, e a conexao vai para o IP
aprovado. Antes a ferramenta resolvia de novo e podia cair em 127.0.0.1."""
from __future__ import annotations

import asyncio

import pytest

from app.api.endpoints import network_tools as NT
from app.api.endpoints import tools as T
from app.api.endpoints import ws as W
from app.core import destino as D
from test_destino_permitido import rede  # noqa: F401  (fixture)


@pytest.fixture
def rebinding(rede, monkeypatch):
    """1a consulta: IP publico. Da 2a em diante: loopback."""
    respostas = iter(["8.8.8.8"])

    def _resolve(nome, porta, *a, **k):
        return [(2, 1, 6, "", (next(respostas, "127.0.0.1"), 0))]

    monkeypatch.setattr(D.socket, "getaddrinfo", _resolve)


def test_ferramenta_tcp_conecta_no_ip_aprovado(rebinding, monkeypatch):
    conectados = []

    async def _tcp(host, port, timeout):
        conectados.append(host)
        return {"target": host, "port": port, "open": False}

    monkeypatch.setattr(NT, "_tcp_check_safe", _tcp)
    res = asyncio.run(NT.api_network_tools_run({"test": "tcp", "targets": "cdn.exemplo.test", "ports": "443"}))
    assert conectados == ["8.8.8.8"]
    assert res["result"]["items"][0]["target"] == "cdn.exemplo.test"  # o operador ve o que digitou


class _Resposta:
    status_code = 200
    url = "http://8.8.8.8/"
    headers = {}


class _ClienteHttp:
    pedidos = []

    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        self.pedidos.append((url, headers))
        return _Resposta()


def test_ferramenta_http_pede_no_ip_aprovado_com_host_original(rebinding, monkeypatch):
    _ClienteHttp.pedidos = []
    monkeypatch.setattr(NT.httpx, "AsyncClient", _ClienteHttp)
    asyncio.run(NT.api_network_tools_run({"test": "http", "targets": "http://cdn.exemplo.test:8080/x"}))
    assert _ClienteHttp.pedidos == [("http://8.8.8.8:8080/x", {"Host": "cdn.exemplo.test:8080"})]


def test_ferramenta_http_com_ip_nao_muda_o_pedido(rede, monkeypatch):
    _ClienteHttp.pedidos = []
    monkeypatch.setattr(NT.httpx, "AsyncClient", _ClienteHttp)
    asyncio.run(NT.api_network_tools_run({"test": "http", "targets": "8.8.8.8", "port": "80"}))
    assert _ClienteHttp.pedidos == [("http://8.8.8.8:80", None)]


class _Ws:
    def __init__(self):
        self.enviados = []

    async def send_text(self, texto):
        self.enviados.append(texto)

    async def receive_text(self):
        await asyncio.Event().wait()


def test_portscan_conecta_no_ip_aprovado(rebinding, monkeypatch):
    conectados = []

    async def _abre(host, port):
        conectados.append(host)
        raise OSError("sem rota")

    async def _aceita(ws, *, min_role="viewer"):
        return True, {"effective_tenant_slug": "cliente-a"}, {"targets": "cdn.exemplo.test", "ports": "80"}

    monkeypatch.setattr(W.asyncio, "open_connection", _abre)
    monkeypatch.setattr(W, "_accept_ws_session", _aceita)
    asyncio.run(W.ws_portscan(_Ws()))
    assert conectados == ["8.8.8.8"]


def test_descoberta_conecta_no_ip_aprovado(rebinding, monkeypatch):
    conectados = []

    async def _abre(host, port):
        conectados.append(host)
        raise OSError("sem rota")

    monkeypatch.setattr(T.asyncio, "open_connection", _abre)
    asyncio.run(T.api_discovery_run({"targets": "cdn.exemplo.test", "ports": "80"}))
    assert conectados == ["8.8.8.8"]


def test_nome_com_algum_ip_recusado_e_recusado(rede, monkeypatch):
    monkeypatch.setattr(D.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 0)), (2, 1, 6, "", ("127.0.0.1", 0))])
    fixos, recusados = D.destinos_fixados("cliente-a", ["misto.exemplo.test"])
    assert fixos == {} and "misto.exemplo.test" in recusados
