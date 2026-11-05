"""Linha de inventario com IP nao literal nao vira posse, a tela recebe erro
claro, e o save global nao some com linha legitima."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.endpoints import cameras as C
from app.core import destino as D
from app.services import connector_service as cs
from test_destino_permitido import rede  # noqa: F401  (fixture)


@pytest.mark.parametrize("ip", ["cam.atacante.example", "10.208.261", "181403909", "010.0.0.1"])
def test_ip_nao_literal_nao_passa_no_inventario(rede, monkeypatch, ip):
    monkeypatch.setattr(C, "_camera_row_for_ip", lambda alvo, cid="": {"ip": alvo})
    assert C._ip_in_inventory(ip) is False


def test_ip_literal_e_ip_porta_seguem(rede, monkeypatch):
    monkeypatch.setattr(C, "_camera_row_for_ip", lambda alvo, cid="": {"ip": alvo})
    assert C._ip_in_inventory("192.168.10.5") is True
    assert C._ip_in_inventory("45.164.52.138:81") is True


@pytest.mark.parametrize("ip", ["cam.atacante.example", "10.208.1.5"])
def test_rota_de_save_recusa_com_erro(rede, monkeypatch, ip):
    monkeypatch.setattr(C, "save_inventory_json", lambda *a, **k: pytest.fail("gravou"))
    with pytest.raises(HTTPException) as exc:
        C.api_cameras_save(C.CamerasSaveRequest(cameras=[C.CameraUpdate(ip=ip)]), mode="olt")
    assert exc.value.status_code == 400 and ip in exc.value.detail


def test_save_global_mantem_linha_do_proprio_conector_em_faixa_virtual_alheia(rede):
    linhas = [{"ip": "10.208.1.5", "remote_connector_id": "conn-a"}, {"ip": "10.208.1.6"}]
    assert D.sem_faixa_virtual_alheia("cliente-a", linhas) == [linhas[0]]


def test_save_global_com_conectores_ilegiveis_nao_apaga_nada(rede, monkeypatch):
    def _quebra():
        raise OSError("disco")

    monkeypatch.setattr(cs, "_load_connectors", _quebra)
    linhas = [{"ip": "10.208.1.5"}, {"ip": "192.168.10.9"}]
    assert D.sem_faixa_virtual_alheia("cliente-a", linhas) == linhas
