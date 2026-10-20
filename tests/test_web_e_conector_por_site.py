"""Web do equipamento (ponte do agente e proxy) e acoes de conector respeitam
o perfil por modulo e os sites do usuario -- quando o dono liga o "valer".

Caso real: o grupo-jangadeiros tem dois sites (JANGADEIROS, Ruijie; INCOFORTE,
MikroTik). Um usuario so do JANGADEIROS nao pode abrir a web da camera do
INCOFORTE sabendo o IP, nem coletar/editar o conector de la.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.endpoints import connectors as CE
from app.api.endpoints import maintenance as M
from app.core import permissions as P

OPERADOR = {"id": 7, "role": "operator", "effective_tenant_slug": "grupo-jangadeiros",
            "effective_enabled_modules": None}


@pytest.fixture
def regras(monkeypatch):
    """Usuario 7 restrito ao site JANGADEIROS; perfis do cliente sem o banco."""
    estado = {"modo": "valer", "dados": {"users": {"7": {"sites": ["JANGADEIROS"]}}, "profiles": {}}}
    monkeypatch.setattr(P, "modo", lambda: estado["modo"])
    monkeypatch.setattr(P, "carregar_perfis", lambda slug, usar_cache=True: estado["dados"])
    return estado


def _alvo(monkeypatch, modulo, site):
    monkeypatch.setattr(M, "_alvo_web", lambda ip: (modulo, site))


def test_web_de_outro_site_negada_e_do_proprio_liberada(regras, monkeypatch):
    _alvo(monkeypatch, "cameras", "INCOFORTE")
    ok, motivo = M.web_liberada_para(OPERADOR, "192.168.20.40")
    assert not ok and "INCOFORTE" in motivo
    _alvo(monkeypatch, "cameras", "JANGADEIROS")
    assert M.web_liberada_para(OPERADOR, "172.16.81.3") == (True, "")


def test_web_sem_permissao_no_modulo(regras, monkeypatch):
    regras["dados"]["users"]["7"]["overrides"] = {"gravadores": "ver"}
    _alvo(monkeypatch, "gravadores", "JANGADEIROS")
    ok, motivo = M.web_liberada_para(OPERADOR, "172.16.80.201")
    assert not ok and "gravadores" in motivo  # so "ver": abrir a web e operar


def test_equipamento_sem_site_fica_de_fora_para_quem_e_restrito(regras, monkeypatch):
    _alvo(monkeypatch, "cameras", "")
    assert M.web_liberada_para(OPERADOR, "10.0.0.9")[0] is False


def test_em_sombra_nada_muda(regras, monkeypatch):
    regras["modo"] = "sombra"
    regras["dados"]["users"]["7"]["overrides"] = {"cameras": "sem_acesso"}
    _alvo(monkeypatch, "cameras", "INCOFORTE")
    assert M.web_liberada_para(OPERADOR, "192.168.20.40") == (True, "")


def test_dono_e_sem_usuario_sempre_passam(regras, monkeypatch):
    _alvo(monkeypatch, "cameras", "INCOFORTE")
    assert M.web_liberada_para({**OPERADOR, "role": "owner"}, "192.168.20.40")[0]
    assert M.web_liberada_para(None, "192.168.20.40")[0]  # autenticacao desligada


def test_alvo_web_reconhece_cada_tipo(monkeypatch):
    for nome in ("_camera_row_for_ip", "_recorder_row_for_host", "_access_device_for_host"):
        monkeypatch.setattr(M, nome, lambda ip: None)
    for nome in ("_switch_connector_for_ip", "_tr069_onu_connector_for_ip"):
        monkeypatch.setattr(M, nome, lambda ip: None)
    monkeypatch.setattr(M, "_connector_tunnel_ip_owner", lambda ip: "")
    monkeypatch.setattr(M, "_ruijie_gateway_owner", lambda ip: "gw" if ip == "172.16.80.1" else "")
    monkeypatch.setattr("app.services.connector_service.get_connector",
                        lambda cid, include_token=False, enforce_tenant=False: {"id": cid, "site": "JANGADEIROS"})
    assert M._alvo_web("172.16.80.1") == ("conectores", "JANGADEIROS")  # eWeb do Ruijie
    monkeypatch.setattr(M, "_recorder_row_for_host", lambda ip: {"host": ip, "site": "INCOFORTE"})
    assert M._alvo_web("192.168.20.200") == ("gravadores", "INCOFORTE")
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip: {"ip": ip, "local": "INCOFORTE"})
    assert M._alvo_web("192.168.20.40") == ("cameras", "INCOFORTE")
    for nome in ("_camera_row_for_ip", "_recorder_row_for_host"):
        monkeypatch.setattr(M, nome, lambda ip: None)
    assert M._alvo_web("10.9.9.9") == ("", "")


# ------------------------------------------------------------------ conectores
CONECTORES = {"gw": {"id": "gw", "site": "JANGADEIROS"}, "mk": {"id": "mk", "site": "INCOFORTE"}}


def _req(user, cid=""):
    return SimpleNamespace(state=SimpleNamespace(current_user=user), path_params={"connector_id": cid} if cid else {})


@pytest.fixture
def conectores(monkeypatch):
    monkeypatch.setattr(CE, "get_connector", lambda cid, include_token=False, enforce_tenant=False: CONECTORES.get(cid))
    monkeypatch.setattr(CE, "list_connectors", lambda include_token=False: {"connectors": list(CONECTORES.values())})


def test_acao_no_conector_de_outro_site_negada(regras, conectores):
    with pytest.raises(HTTPException) as e:
        CE._site_do_conector_liberado(_req(OPERADOR, "mk"))  # editar/Coletar LAN/VPN do INCOFORTE
    assert e.value.status_code == 403
    CE._site_do_conector_liberado(_req(OPERADOR, "gw"))  # o do proprio site passa
    CE._site_do_conector_liberado(_req(OPERADOR))  # rota sem connector_id (agente) passa


def test_lista_e_job_respeitam_o_site(regras, conectores):
    assert [c["id"] for c in CE.api_connectors_list(_req(OPERADOR))["connectors"]] == ["gw"]
    with pytest.raises(HTTPException):
        CE.api_connector_create_job({"connector_id": "mk", "type": "ping_many"}, _req(OPERADOR))


def test_conector_em_sombra_lista_tudo(regras, conectores):
    regras["modo"] = "sombra"
    assert len(CE.api_connectors_list(_req(OPERADOR))["connectors"]) == 2
    CE._site_do_conector_liberado(_req(OPERADOR, "mk"))
