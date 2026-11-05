"""Linha no inventario nao prova posse de rede: POST /api/cameras/save gravava
10.250.0.x e liberava. O dono vem do conector do cliente."""
from __future__ import annotations

import pytest

from app.api.endpoints import maintenance as M
from app.core import destino as D
from app.services import connector_routing_vnat as vnat
from app.services import connector_service as cs
from test_destino_permitido import CONECTORES, rede  # noqa: F401  (fixture)


@pytest.fixture
def inventario(rede, monkeypatch):
    """Inventario real do helper; as outras fontes de equipamento vazias."""
    linhas = [
        {"ip": "10.99.0.1"},                                     # sem conector
        {"ip": "10.99.0.2", "remote_connector_id": "conn-a"},    # conector dele
        {"ip": "10.99.0.3", "connector_id": "conn-b"},           # conector alheio
    ]
    monkeypatch.setattr(M, "_equipamentos_com_conector", ORIGINAL)  # a fixture rede troca o helper
    monkeypatch.setattr(M, "_ip_belongs_to_current_tenant", lambda ip: True)  # o inventario diz que e dele
    monkeypatch.setattr(M, "load_inventory_json", lambda mode="olt": linhas if mode == "olt" else [])
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip, c="": None)
    return linhas


ORIGINAL = M._equipamentos_com_conector


def test_linha_sem_conector_nao_prova_posse_para_cliente_com_conector(inventario):
    ok, motivo = D.destino_permitido("cliente-a", "10.99.0.1")
    assert not ok and "nao pertence" in motivo


def test_linha_com_conector_do_cliente_prova_posse(inventario):
    assert D.destino_permitido("cliente-a", "10.99.0.2") == (True, "")


def test_linha_com_conector_de_outro_cliente_nao_prova_posse(inventario):
    assert D.destino_permitido("cliente-a", "10.99.0.3")[0] is False


def test_wg_compartilhada_bloqueada_por_padrao(rede, monkeypatch):
    monkeypatch.delenv("DESTINO_REDES_BLOQUEADAS")
    ok, motivo = D.destino_permitido("cliente-a", "10.250.0.7")
    assert not ok and "interna" in motivo
    monkeypatch.setenv("DESTINO_REDES_BLOQUEADAS", "10.77.0.0/16")
    assert D.destino_permitido("cliente-a", "10.77.0.1")[0] is False


@pytest.fixture
def sem_conector(rede, monkeypatch):
    linhas = [dict(c) for c in CONECTORES]
    linhas.append({"id": "conn-t", "tenant_slug": "cliente-b", "tunnel": {"client_address": "10.201.0.7/31"}})
    monkeypatch.setattr(cs, "_load_connectors", lambda: linhas)


def test_cliente_sem_conector_na_rede_direta_continua(sem_conector):
    assert D.destino_permitido("cliente-c", "192.168.77.5")[0] is True


def test_cliente_sem_conector_nao_alcanca_o_que_e_de_outro(sem_conector, monkeypatch):
    assert D.destino_permitido("cliente-c", "10.208.1.5")[0] is False  # faixa virtual
    assert D.destino_permitido("cliente-c", "10.201.0.7")[0] is False  # roteador de outro cliente
    assert D.destino_permitido("cliente-c", "127.0.0.1")[0] is False
    monkeypatch.delenv("DESTINO_REDES_BLOQUEADAS")
    assert D.destino_permitido("cliente-c", "10.250.0.7")[0] is False


def test_rede_direta_pode_ser_desligada(sem_conector, monkeypatch):
    monkeypatch.setenv("DESTINO_REDE_DIRETA", "nunca")
    assert D.destino_permitido("cliente-c", "192.168.77.5")[0] is False


def test_cliente_sem_conector_nao_alcanca_lan_de_outro(sem_conector):
    ok, motivo = D.destino_permitido("cliente-c", "192.168.10.5")
    assert not ok and "outro cliente" in motivo


def test_mapa_vazio_nao_abre_a_faixa_virtual(rede, monkeypatch):
    monkeypatch.setattr(vnat, "_load_map", lambda: {})
    assert D.destino_permitido("cliente-a", "10.208.1.5")[0] is False
    assert D.destino_permitido("cliente-c", "10.211.5.252")[0] is False


def test_lan_real_dentro_da_faixa_virtual_segue_do_dono(rede, monkeypatch):
    linhas = [{"id": "conn-a", "tenant_slug": "cliente-a", "host": {"lan_networks": ["10.220.0.0/24"]}}]
    monkeypatch.setattr(cs, "_load_connectors", lambda: linhas)
    assert D.destino_permitido("cliente-a", "10.220.0.9")[0] is True


def test_mapa_ilegivel_nega(rede, monkeypatch):
    def _quebra():
        raise OSError("disco")

    monkeypatch.setattr(vnat, "_load_map", _quebra)
    assert D.destino_permitido("cliente-a", "192.168.10.5")[0] is False
    assert D.destino_permitido("cliente-a", "8.8.8.8")[0] is True


def test_falha_ao_ler_conectores_nao_vira_cliente_sem_conector(rede, monkeypatch):
    def _quebra():
        raise OSError("disco")

    monkeypatch.setattr(cs, "_load_connectors", _quebra)
    assert D.destino_permitido("cliente-c", "192.168.77.5")[0] is False
