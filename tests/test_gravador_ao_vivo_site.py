"""Video de gravador (ao vivo e gravacao) so abre o par IP + conector do cadastro,
e de site que a pessoa acessa. IP privado se repete entre lojas; o IP e o
conector vem do navegador."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.endpoints import deployments as D
from app.api.endpoints import recorder_driver as R
from app.core import permissions
from app.services import nvr_ai_service

# duas lojas com o MESMO IP privado de gravador, cada uma atras do seu conector
CADASTRO = [
    {"host": "192.168.1.10", "channel": 1, "remote_connector_id": "conA", "site": "LOJA A"},
    {"host": "192.168.1.10", "channel": 1, "remote_connector_id": "conB", "site": "LOJA B"},
    {"host": "192.168.24.227", "channel": 3, "remote_connector_id": "conV", "site": "VITAL 106"},
]


@pytest.fixture()
def cadastro(monkeypatch):
    monkeypatch.setattr(nvr_ai_service, "_read_nvr_inventory", lambda: list(CADASTRO))
    sessao = {"sites": None}
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: sessao["sites"])
    return sessao


def _proibido(host, conector):
    with pytest.raises(HTTPException) as exc:
        R.gravador_liberado(host, conector)
    assert exc.value.status_code == 403


def test_sem_restricao_usa_o_conector_do_cadastro(cadastro):
    assert R.gravador_liberado("192.168.24.227", "") == "conV"
    assert R.gravador_liberado("192.168.24.227", "conV") == "conV"
    assert R.gravador_liberado("192.168.1.10", "conB") == "conB"
    assert R.gravador_liberado("192.168.1.10", "") == ""   # dois cadastros: quem chama decide, como antes
    assert R.gravador_liberado("10.9.9.9", "conX") == "conX"  # fora do cadastro: segue como antes
    _proibido("192.168.24.227", "conA")                    # conector que nao e o desse gravador


def test_restrito_nao_chega_ao_gravador_de_outra_loja_com_o_mesmo_ip(cadastro):
    cadastro["sites"] = ["LOJA A"]
    assert R.gravador_liberado("192.168.1.10", "conA") == "conA"
    assert R.gravador_liberado("192.168.1.10", "") == "conA"
    _proibido("192.168.1.10", "conB")
    _proibido("192.168.24.227", "conV")
    _proibido("10.9.9.9", "conX")


def test_ao_vivo_confere_antes_de_buscar_a_senha(cadastro, monkeypatch):
    cadastro["sites"] = ["LOJA A"]
    chamou = []
    monkeypatch.setattr(D, "_credencial_gravador", lambda *a, **k: chamou.append(1) or ("admin", "x"))
    with pytest.raises(HTTPException) as exc:
        D.api_deployments_recorder_live_stream({"recorder_host": "192.168.1.10", "canal": 1, "connector_id": "conB"})
    assert exc.value.status_code == 403 and chamou == []


def test_ao_vivo_sem_restricao_segue_o_caminho_de_sempre(cadastro, monkeypatch):
    monkeypatch.setattr(D, "_credencial_gravador", lambda *a, **k: ("admin", ""))
    with pytest.raises(HTTPException) as exc:
        D.api_deployments_recorder_live_stream({"recorder_host": "192.168.24.227", "canal": 3, "connector_id": "conV"})
    assert exc.value.status_code == 428  # sem senha guardada: o mesmo de antes
