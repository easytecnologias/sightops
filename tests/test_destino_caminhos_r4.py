"""R1, 4a rodada: caminhos que conectavam no IP real sem passar por destino, e
conector COM mapa com IP fora dele."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.endpoints import deployments as DP
from app.api.endpoints import dvr as DV
from app.api.endpoints import maintenance as M
from app.api.endpoints import nvr as NV
from app.core import destino as D
from app.core import guarda_destino as GD
from app.services import access_control_device as AC
from app.services import access_control_store as AS
from app.services import camera_senha_lote as SL
from app.services import connector_routing_vnat as vnat
from app.services import connector_service as vnat_cs
from test_destino_permitido import rede  # noqa: F401  (fixture)


@pytest.fixture
def base(rede, monkeypatch):
    monkeypatch.setattr(vnat, "_dono_cache", {})
    monkeypatch.setattr(D, "_finais", {}, raising=False)
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip, hint="": {})
    monkeypatch.setattr(NV, "_recorder_connector_for_host", lambda ip: "")
    monkeypatch.setattr(DV, "_recorder_connector_for_host", lambda ip: "")


# ---------------------------------------------------------------- change_ip
@pytest.mark.parametrize("novo", ["10.208.1.5", "192.168.10.20", "127.0.0.1"])
def test_confirmar_troca_de_ip_nao_manda_senha_para_ip_alheio(base, monkeypatch, novo):
    monkeypatch.setattr(M.requests, "get", lambda *a, **k: pytest.fail("mandou a senha"))
    with pytest.raises(HTTPException) as exc:
        M.maintenance_change_ip_confirmar({"ip": "10.208.0.9", "new_ip": novo, "user": "a", "pass": "b"})
    assert exc.value.status_code == 403


def test_confirmar_troca_pelo_conector_segue(base, monkeypatch):
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip, hint="": {"remote_connector_id": "conn-a"})
    alvos = []

    def _get(url, **k):
        alvos.append(url)
        raise OSError("aguardando")

    monkeypatch.setattr(M.requests, "get", _get)
    r = M.maintenance_change_ip_confirmar({"ip": "192.168.10.9", "new_ip": "192.168.10.20", "user": "a", "pass": "b"})
    assert r.get("aguardando") and alvos and all("10.208.0.20" in u for u in alvos)


# -------------------------------------------------------------- senha em lote
def test_senha_em_lote_so_vai_ao_ip_conferido(base):
    assert SL._alcance("192.168.10.9", "conn-a") == "10.208.0.9"
    assert SL._alcance("192.168.10.9", "") == ""   # real de LAN isolada, sem conector
    assert SL._alcance("10.208.1.5", "") == ""     # virtual de outro cliente
    assert SL._alcance("192.168.10.9", "conn-b") == ""
    assert SL._alcance("10.208.0.9", "") == "10.208.0.9"


# --------------------------------------------------------------- controladora
@pytest.mark.parametrize("host", ["10.208.1.5", "192.168.10.9", "127.0.0.1", "169.254.169.254"])
def test_controladora_sem_conector_nao_conecta_em_destino_recusado(base, monkeypatch, host):
    monkeypatch.setattr(AC.requests, "get", lambda *a, **k: pytest.fail("conectou"))
    monkeypatch.setattr(AC.requests, "post", lambda *a, **k: pytest.fail("conectou"))
    aparelho = {"host": host, "username": "a", "password": "b"}
    with pytest.raises(HTTPException) as exc:
        AC._get(aparelho, "/cgi-bin/x")
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        AC._post_json(aparelho, "/cgi-bin/x", {}, "teste")
    assert exc.value.status_code == 403


def test_controladora_do_cliente_segue_pelo_virtual_e_fora_do_mapa_pelo_agente(base, monkeypatch):
    assert AC._base_url_direct({"host": "192.168.10.9", "connector_id": "conn-a"}) == "http://10.208.0.9"
    assert AC._has_vnat_mapping({"host": "192.168.10.9", "connector_id": "conn-a"}) is True
    assert AC._has_vnat_mapping({"host": "10.99.0.9", "connector_id": "conn-a"}) is False  # vai pelo agente


@pytest.mark.parametrize("corpo", [{"host": "10.208.1.5"}, {"host": "192.168.10.9"},
                                   {"host": "192.168.10.9", "connector_id": "conn-b"}])
def test_cadastro_de_controladora_recusa_host_alheio(base, monkeypatch, corpo):
    monkeypatch.setattr(AS, "ensure_access_control_schema", lambda: None)
    monkeypatch.setattr(AS.db_store, "_conn", lambda: pytest.fail("gravou"))
    with pytest.raises(ValueError):
        AS.save_device({"name": "porta", **corpo})


# ------------------------------------------------------------------ gravador
@pytest.mark.parametrize("mod", [NV, DV])
def test_gravador_confere_o_ip_final(base, monkeypatch, mod):
    for ip in ("10.208.1.5", "192.168.10.20"):
        with pytest.raises(HTTPException) as exc:
            mod._reach_recorder(ip)
        assert exc.value.status_code == 403
    monkeypatch.setattr(mod, "_recorder_connector_for_host", lambda ip: "conn-a")
    assert mod._reach_recorder("192.168.10.9") == "10.208.0.9"


def test_guarda_acha_o_conector_no_inventario_de_dvr(base, monkeypatch):
    monkeypatch.setattr(DV, "_recorder_connector_for_host", lambda ip: "conn-a")
    assert GD._conector_do_gravador("192.168.10.9") == "conn-a"


def test_commit_camera_nao_grava_virtual_alheio(base, monkeypatch):
    monkeypatch.setattr(DP, "save_inventory_json", lambda *a, **k: pytest.fail("gravou"))
    monkeypatch.setattr(DP, "load_inventory_json", lambda mode="olt": [])
    with pytest.raises(HTTPException) as exc:
        DP.api_deployments_commit_camera({"camera_ip": "10.208.1.5", "camera_title": "x"})
    assert exc.value.status_code == 403


# ---------------------------------------------------------------- fora do mapa
def test_conector_com_mapa_e_ip_fora_dele_bloqueia(base):
    assert vnat.virtual_ip_for("conn-a", "10.99.0.1") == vnat.IP_BLOQUEADO
    assert vnat.fora_do_mapa("conn-a", "10.99.0.1") is True
    assert vnat.fora_do_mapa("conn-b", "10.99.0.1") is False  # de outro cliente: outra mensagem
    assert vnat.virtual_ip_for("conn-a", "10.208.0.9") == "10.208.0.9"  # ja virtual
    assert vnat.virtual_ip_for("conn-a", "8.8.8.8") == "8.8.8.8"        # internet
    assert vnat.virtual_ip_for("conn-a", "10.201.0.7") == "10.201.0.7"  # transito dele


def test_alvo_de_varredura_fora_do_mapa_fica_para_o_mikrotik(base):
    assert vnat.virtualize_target("conn-a", "10.99.0.0/24") == "10.99.0.0/24"
    assert vnat.virtualize_target("conn-a", "10.99.0.5") == "10.99.0.5"
    assert vnat.virtualize_target("conn-a", "192.168.10.0/24") == "10.208.0.0/24"


def test_tunel_compartilhado_nao_vira_dono_pelo_bloqueio(base, monkeypatch):
    monkeypatch.setattr(vnat_cs, "list_connectors", lambda *a, **k: {"connectors": [
        {"id": "conn-a", "tunnel": {"client_address": "10.250.0.5/32"}}]})
    assert M._connector_tunnel_ip_owner("10.250.0.5") == ""
