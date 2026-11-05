"""R1: o aviso "client_lans sobrepoe LAN de outro cliente" saia a cada
requisicao, inclusive para LAN que ja esta no mapa vnat do proprio conector
(RADS Mata Grande, Escola M. Conceicao). A decisao de acesso nao muda."""
from __future__ import annotations

import logging

import pytest

from app.core import destino as D
from app.services import connector_service as cs
from test_destino_permitido import CONECTORES, rede  # noqa: F401  (fixture)


@pytest.fixture
def lans_digitadas(rede, monkeypatch):
    linhas = [dict(c) for c in CONECTORES]
    linhas[0] = {**linhas[0], "tunnel": {"client_lans": "192.168.10.0/24, 10.40.0.0/24"}}
    linhas[1] = {**linhas[1], "host": {"lan_networks": ["192.168.10.0/24", "10.40.0.0/16"]}}
    monkeypatch.setattr(cs, "_load_connectors", lambda: [dict(c) for c in linhas])
    monkeypatch.setattr(D, "_AVISADAS", set(), raising=False)


def test_lan_digitada_ja_no_mapa_nao_avisa_e_a_outra_avisa_uma_vez(lans_digitadas, caplog):
    with caplog.at_level(logging.WARNING, logger=D.logger.name):
        for _ in range(3):
            assert D.destino_permitido("cliente-a", "10.40.0.5")[0] is False  # decisao nao muda
            assert D.destino_permitido("cliente-a", "10.208.0.5")[0] is True
    avisos = [r.getMessage() for r in caplog.records if "client_lans" in r.getMessage()]
    assert avisos == ["destino: client_lans 10.40.0.0/24 do conector conn-a sobrepoe LAN de outro cliente -- ignorada"]
