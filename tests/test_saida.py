"""Trava de saida: conexao TCP ao IP real de LAN de conector isolado nao sai do
processo, venha de onde vier (requests, socket, asyncio, laco sem cliente)."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket

import pytest
import requests

from app.core import destino as D
from app.core import saida as S
from app.services import connector_routing_vnat as vnat

_N = ipaddress.ip_network
MAPA = {"conn-a": [(_N("192.168.10.0/24"), _N("10.208.0.0/24"))],
        "conn-b": [(_N("10.0.0.0/23"), _N("10.208.2.0/23"))]}


@pytest.fixture
def trava(monkeypatch):
    """Rede de verdade trocada por uma lista: nada sai da maquina do teste."""
    tentou = []
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    # loopback de verdade: o asyncio no Windows monta o socketpair por ele
    def _falso(self, end):
        return connect(self, end) if end[0] == "127.0.0.1" else tentou.append(end)

    def _falso_ex(self, end):
        return connect_ex(self, end) if end[0] == "127.0.0.1" else (tentou.append(end) or 0)

    monkeypatch.setattr(socket.socket, "connect", _falso)
    monkeypatch.setattr(socket.socket, "connect_ex", _falso_ex)
    monkeypatch.setattr(vnat, "_load_map", lambda: MAPA)
    monkeypatch.setattr(D, "_redes_do_container", lambda caminho="": [_N("172.30.0.0/16"), _N("10.0.1.0/24")])
    monkeypatch.setattr(S, "_nomes_de_servico", lambda: {"192.168.10.77"})
    monkeypatch.setenv("SIGHTOPS_SAIDA_MODO", "valer")
    monkeypatch.delenv("SIGHTOPS_SAIDA_PERMITIDA", raising=False)
    S.desinstalar()
    S.instalar()
    S._recarregando.acquire(timeout=5)  # espera a carga em fundo
    S._recarregando.release()
    S.recarregar()
    yield tentou
    S.desinstalar()


def _tcp():
    return socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_valer_recusa_socket_e_requests_sem_tocar_a_rede(trava):
    with _tcp() as s, pytest.raises(S.SaidaRecusada):
        s.connect(("192.168.10.9", 80))
    with _tcp() as s:
        assert s.connect_ex(("10.0.0.5", 80)) != 0
    with pytest.raises(requests.ConnectionError):
        requests.get("http://192.168.10.9/", timeout=1)
    with pytest.raises(OSError):
        socket.create_connection(("192.168.10.9", 80), timeout=1)
    assert trava == []


def test_valer_recusa_asyncio(trava):
    async def _abre():
        await asyncio.open_connection("192.168.10.9", 80)

    with pytest.raises(OSError):
        asyncio.run(_abre())
    assert trava == []


@pytest.mark.parametrize("ip", ["10.208.0.9", "8.8.8.8", "172.30.0.5",
                                "10.0.1.5",        # bridge do Docker sobre LAN isolada
                                "192.168.10.77"])  # servico configurado
def test_excecoes_passam(trava, ip):
    with _tcp() as s:
        s.connect((ip, 80))
    assert trava == [(ip, 80)]


def test_loopback_nunca_e_recusado(trava):
    assert not S.recusar("127.0.0.1")


def test_permitida_por_env(trava, monkeypatch):
    monkeypatch.setenv("SIGHTOPS_SAIDA_PERMITIDA", "192.168.10.128/25")
    S.recarregar()
    with _tcp() as s:
        s.connect(("192.168.10.200", 80))
    assert trava == [("192.168.10.200", 80)]


def test_udp_nao_e_interceptado(trava):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.168.10.9", 53))
    assert trava == [("192.168.10.9", 53)]


def test_aviso_conecta_e_loga_uma_vez_com_cliente_e_origem(trava, monkeypatch, caplog):
    monkeypatch.setenv("SIGHTOPS_SAIDA_MODO", "aviso")
    with caplog.at_level(logging.WARNING, logger=S.logger.name):
        for _ in range(3):
            with _tcp() as s:
                s.connect(("192.168.10.9", 80))
    assert len(trava) == 3
    avisos = [r.getMessage() for r in caplog.records if "LAN isolada" in r.getMessage()]
    assert len(avisos) == 1
    assert "192.168.10.9:80" in avisos[0] and "(sem cliente)" in avisos[0]


def test_desligado_nao_instala(monkeypatch):
    S.desinstalar()
    monkeypatch.setenv("SIGHTOPS_SAIDA_MODO", "desligado")
    original = socket.socket.connect
    assert S.instalar() == "desligado"
    assert socket.socket.connect is original


def test_desligar_em_uso_deixa_passar(trava, monkeypatch):
    monkeypatch.setenv("SIGHTOPS_SAIDA_MODO", "desligado")
    with _tcp() as s:
        s.connect(("192.168.10.9", 80))
    assert len(trava) == 1


def test_lan_nova_no_mapa_vale_na_recarga(trava, monkeypatch):
    assert not S.recusar("10.45.0.7")
    monkeypatch.setattr(vnat, "_load_map", lambda: {**MAPA, "conn-c": [(_N("10.45.0.0/24"), _N("10.208.9.0/24"))]})
    S.recarregar(com_nomes=False)
    assert S.recusar("10.45.0.7")


def test_nome_de_servico_que_parou_de_resolver_continua_permitido(trava, monkeypatch):
    monkeypatch.setattr(S, "_nomes_de_servico", lambda: set())
    S.recarregar()
    assert not S.recusar("192.168.10.77")


def test_urls_do_ambiente_e_padrao_viram_servico(monkeypatch):
    monkeypatch.setenv("SIGHTOPS_EVOLUTION_URL", "http://10.10.12.7:8090")
    monkeypatch.setenv("DATABASE_HOST", "banco-x:5432")
    monkeypatch.setattr(S, "_hosts_das_configuracoes", lambda: {"zabbix.exemplo"})
    nomes = S._nomes_de_servico()
    assert {"10.10.12.7", "banco-x", "go2rtc", "zabbix.exemplo"} <= nomes
