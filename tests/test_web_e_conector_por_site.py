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


# ------------------------------------------------- site da ROTA (revisor, 2a rodada)
def test_ip_camera_de_um_site_e_gravador_de_outro_vale_o_site_da_rota(regras, monkeypatch):
    """Revisor: a ponte usa o conector do GRAVADOR (rec_cid) no _reach; conferir
    so o site da ficha da camera liberava o site A e o pacote ia ao B."""
    _alvo(monkeypatch, "cameras", "JANGADEIROS")
    monkeypatch.setattr(M, "_connector_for", lambda ip, hint="": hint or "gw")
    monkeypatch.setattr(M, "_site_do_conector",
                        lambda cid: {"gw": "JANGADEIROS", "mk": "INCOFORTE"}.get(cid, ""))
    assert M.web_liberada_para(OPERADOR, "192.168.1.10")[0]                    # proxy: rota pelo gw
    ok, motivo = M.web_liberada_para(OPERADOR, "192.168.1.10", conector_hint="mk")  # ponte: gravador do INCOFORTE
    assert not ok and "INCOFORTE" in motivo


def test_controladora_com_site_a_e_conector_de_b_nao_vira_pivo(regras, monkeypatch):
    _alvo(monkeypatch, "acesso", "JANGADEIROS")       # site digitado no cadastro
    monkeypatch.setattr(M, "_connector_for", lambda ip, hint="": "mk")   # mas sai pelo conector de B
    monkeypatch.setattr(M, "_site_do_conector", lambda cid: "INCOFORTE")
    assert M.web_liberada_para(OPERADOR, "192.168.20.200")[0] is False


# ------------------------------------------------------------------ conectores
CONECTORES = {"gw": {"id": "gw", "site": "JANGADEIROS"}, "mk": {"id": "mk", "site": "INCOFORTE"}}


def _req(user, cid=""):
    return SimpleNamespace(state=SimpleNamespace(current_user=user), path_params={"connector_id": cid} if cid else {})


@pytest.fixture
def conectores(monkeypatch, tmp_path):
    from app.services import connector_service as CS
    monkeypatch.setattr(CS, "CONNECTORS_PATH", tmp_path / "connectors.json")
    monkeypatch.setattr(CS, "DATA_DIR", tmp_path)
    monkeypatch.setattr(CS, "get_current_tenant_slug", lambda: "grupo-jangadeiros")
    CS._save_connectors([{**c, "tenant_slug": "grupo-jangadeiros", "type": "routeros"} for c in CONECTORES.values()])
    monkeypatch.setattr(CE, "get_connector", lambda cid, include_token=False, enforce_tenant=False: CONECTORES.get(cid))
    return CS


def test_acao_no_conector_de_outro_site_negada(regras, conectores):
    with pytest.raises(HTTPException) as e:
        CE._site_do_conector_liberado(_req(OPERADOR, "mk"))  # editar/Coletar LAN/VPN do INCOFORTE
    assert e.value.status_code == 403
    CE._site_do_conector_liberado(_req(OPERADOR, "gw"))  # o do proprio site passa
    CE._site_do_conector_liberado(_req(OPERADOR))  # rota sem connector_id (agente) passa


def test_lista_e_job_respeitam_o_site(regras, conectores):
    lista = CE.api_connectors_list(_req(OPERADOR))
    assert [c["id"] for c in lista["connectors"]] == ["gw"] and lista["count"] == 1  # contagem nao vaza
    with pytest.raises(HTTPException):
        CE.api_connector_create_job({"connector_id": "mk", "type": "ping_many"}, _req(OPERADOR))


def test_conector_em_sombra_lista_tudo(regras, conectores):
    regras["modo"] = "sombra"
    assert len(CE.api_connectors_list(_req(OPERADOR))["connectors"]) == 2
    CE._site_do_conector_liberado(_req(OPERADOR, "mk"))


def test_ativacao_e_tuneis_respeitam_o_site(regras, conectores, monkeypatch):
    from app.api.endpoints import camera_activation as CA
    from app.api.endpoints import network_map as NM
    monkeypatch.setattr(conectores, "get_connector",
                        lambda cid, include_token=False, enforce_tenant=False: CONECTORES.get(cid))
    with pytest.raises(HTTPException) as e:
        CA.api_activation_scan({"connector_id": "mk"}, _req(OPERADOR))   # varrer pelo conector do INCOFORTE
    assert e.value.status_code == 403
    for rota in (CA.api_activation_reboot, CA.api_activation_locate, CA.api_activation_run):
        with pytest.raises(HTTPException) as e:
            rota({"connector_id": "mk"}, _req(OPERADOR))
        assert e.value.status_code == 403
    vistos = {c["id"] for c in conectores.list_connectors(user=OPERADOR)["connectors"]}
    assert vistos == {"gw"}


# ------------------------------------------------ lotes, rotas por IP e /network/path
import asyncio  # noqa: E402


class _ReqAsync:
    def __init__(self, user, path, corpo=None, metodo="POST", path_params=None):
        self.state = SimpleNamespace(current_user=user)
        self.url = SimpleNamespace(path=path)
        self.method = metodo
        self.path_params = path_params or {}
        self._corpo = corpo

    async def json(self):
        return self._corpo


def test_ips_de_origem_de_cada_formato_de_lote():
    assert M._ips_do_lote({"ips": ["10.0.0.1", "10.0.0.2"]}) == ["10.0.0.1", "10.0.0.2"]
    assert M._ips_do_lote({"targets": [{"old_ip": "10.0.0.3", "new_ip": "10.0.0.99"}]}) == ["10.0.0.3"]
    assert M._ips_do_lote({"itens": [{"ip": "10.0.0.4", "new_ip": "10.0.0.98"}]}) == ["10.0.0.4"]
    assert M._ips_do_lote({"prefix": "10.0.0.", "start_octet": 5, "end_octet": 7}) == ["10.0.0.5", "10.0.0.6", "10.0.0.7"]
    assert M._ips_do_lote("lixo") == []


def test_lote_com_um_ip_de_outro_site_e_recusado_inteiro(regras, monkeypatch):
    sites = {"172.16.81.3": "JANGADEIROS", "192.168.20.40": "INCOFORTE"}
    monkeypatch.setattr(M, "_alvo_web", lambda ip: ("cameras", sites.get(ip, "")))
    monkeypatch.setattr(M, "_connector_for", lambda ip, hint="": "")
    ok = _ReqAsync(OPERADOR, "/api/maintenance/batch/reboot", {"ips": ["172.16.81.3"]})
    asyncio.run(M._conferir_lote(ok))
    misto = _ReqAsync(OPERADOR, "/api/maintenance/batch/reboot", {"ips": ["172.16.81.3", "192.168.20.40"]})
    with pytest.raises(HTTPException) as e:
        asyncio.run(M._conferir_lote(misto))
    assert e.value.status_code == 403 and "192.168.20.40" in e.value.detail


def test_video_ao_vivo_por_ip_respeita_site_e_a_dica_do_conector(regras, monkeypatch):
    _alvo(monkeypatch, "cameras", "JANGADEIROS")
    monkeypatch.setattr(M, "_connector_for", lambda ip, hint="": hint or "gw")
    monkeypatch.setattr(M, "_site_do_conector", lambda cid: {"gw": "JANGADEIROS", "mk": "INCOFORTE"}.get(cid, ""))
    asyncio.run(M._conferir_ip_do_caminho(_ReqAsync(OPERADOR, "/api/maintenance/live/1.2.3.4", metodo="GET",
                                                     path_params={"ip": "1.2.3.4"})))
    reg = _ReqAsync(OPERADOR, "/api/maintenance/stream_register/1.2.3.4", {"remote_connector_id": "mk"},
                    path_params={"ip": "1.2.3.4"})
    with pytest.raises(HTTPException):
        asyncio.run(M._conferir_ip_do_caminho(reg))


def test_ip_sem_cadastro_so_para_quem_nao_tem_restricao(regras, monkeypatch):
    _alvo(monkeypatch, "", "")
    assert M.alvo_liberado(OPERADOR, "10.9.9.9", "operar") is False       # restrito por site
    regras["dados"]["users"]["7"]["sites"] = []
    assert M.alvo_liberado(OPERADOR, "10.9.9.9", "operar") is True        # sem restricao


def test_sombra_nao_consulta_inventario(regras, monkeypatch):
    regras["modo"] = "sombra"
    monkeypatch.setattr(M, "_alvo_web", lambda ip: (_ for _ in ()).throw(AssertionError("consultou")))
    assert M.alvo_liberado(OPERADOR, "192.168.20.40", "operar") is True
