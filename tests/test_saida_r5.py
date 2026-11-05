"""R1, 5a rodada: faixa virtual alheia na trava de saida, redirect so no mesmo
host, nome onde se espera IP, OLT no SNMP e no cadastro, defeitos menores."""
from __future__ import annotations

import ipaddress
import logging
import socket
import traceback

import pytest
import requests
from fastapi import HTTPException

from app.api.endpoints import maintenance as M
from app.api.endpoints import olt as O
from app.core import destino as D
from app.core import saida as S
from app.core import tenant_context as TC
from app.models.requests import OltOnuSignalRequest
from app.services import access_control_device as AC
from app.services import access_control_store as AS
from app.services import camera_senha_lote as SL
from app.services import connector_routing_vnat as vnat
from app.services import connector_service as cs
from app.services import olt_registry as OR
from app.services import olt_snmp_health as OS
from app.services import recorder_xray as RX
from test_destino_permitido import rede  # noqa: F401  (fixture)

_N = ipaddress.ip_network
MAPA = {"conn-a": [(_N("192.168.10.0/24"), _N("10.208.0.0/24"))],
        "conn-b": [(_N("192.168.20.0/24"), _N("10.209.128.0/24"))],
        "orfao": [(_N("192.168.30.0/24"), _N("10.209.200.0/24"))]}
LINHAS = [{"id": "conn-a", "tenant_slug": "cliente-a"}, {"id": "conn-b", "tenant_slug": "cliente-b"}]


@pytest.fixture
def estado(monkeypatch):
    monkeypatch.setattr(vnat, "_load_map", lambda: MAPA)
    monkeypatch.setattr(cs, "_load_connectors", lambda: [dict(c) for c in LINHAS])
    monkeypatch.setattr(D, "_redes_do_container", lambda caminho="": [])
    monkeypatch.setattr(S, "_nomes_de_servico", lambda: set())
    S.desinstalar()
    S.recarregar()
    yield
    S.desinstalar()


def _como(cliente):
    return TC.set_current_tenant_slug(cliente)


# ---------------------------------------------------------- 1. faixa virtual
@pytest.mark.parametrize("cliente,esperado", [("cliente-a", True), ("cliente-b", False), ("", False)])
def test_faixa_virtual_so_do_dono(estado, cliente, esperado):
    token = _como(cliente)
    try:
        assert S.recusar("10.209.128.5") is esperado
    finally:
        TC.reset_current_tenant_slug(token)


def test_faixa_virtual_propria_e_conector_sem_cadastro(estado):
    token = _como("cliente-a")
    try:
        assert S.recusar("10.208.0.5") is False
        assert S.recusar("10.209.200.5") is True
    finally:
        TC.reset_current_tenant_slug(token)
    assert S.recusar("10.209.200.5") is False  # laco interno


def test_faixa_virtual_alheia_recusada_no_connect(estado, monkeypatch):
    tentou = []
    monkeypatch.setattr(socket.socket, "connect", lambda self, end: tentou.append(end))
    monkeypatch.setenv("SIGHTOPS_SAIDA_MODO", "valer")
    S.instalar()
    S._recarregando.acquire(timeout=5)
    S._recarregando.release()
    S.recarregar()
    token = _como("cliente-a")
    try:
        with socket.socket() as s, pytest.raises(S.SaidaRecusada):
            s.connect(("10.209.128.5", 80))
        assert tentou == []
    finally:
        TC.reset_current_tenant_slug(token)


# ------------------------------------------------------------ 2. redirect
class _R:
    def __init__(self, codigo=200, local="", texto=""):
        self.status_code, self.text = codigo, texto
        self.headers = {"Location": local} if local else {}


@pytest.fixture
def web(monkeypatch):
    chamadas, respostas = [], []

    def _fake(url, **kw):
        chamadas.append((url, kw))
        return respostas.pop(0) if respostas else _R()

    for metodo in ("get", "post", "put"):
        monkeypatch.setattr(requests, metodo, _fake)
    return chamadas, respostas


def test_redirect_para_outro_host_nao_e_seguido(web):
    chamadas, respostas = web
    respostas.append(_R(302, "http://10.209.128.5/x"))
    assert S.pedir_mesmo_host("get", "http://10.208.0.9/a", timeout=1).status_code == 302
    assert len(chamadas) == 1 and chamadas[0][1]["allow_redirects"] is False


def test_redirect_https_no_mesmo_host_segue(web):
    chamadas, respostas = web
    respostas.extend([_R(302, "https://10.208.0.9/a"), _R(200)])
    assert S.pedir_mesmo_host("get", "http://10.208.0.9/a").status_code == 200
    assert [c[0] for c in chamadas] == ["http://10.208.0.9/a", "https://10.208.0.9/a"]


def test_redirect_em_laco_para(web):
    chamadas, respostas = web
    respostas.extend([_R(302, "/a") for _ in range(9)])
    S.pedir_mesmo_host("get", "http://10.208.0.9/a")
    assert len(chamadas) == 4


def _todos_sem_seguir(chamadas):
    return chamadas and all(kw.get("allow_redirects") is False for _u, kw in chamadas)


@pytest.mark.parametrize("pede", [
    lambda: RX._pedir("http://10.208.0.9/x", "a", "b"),
    lambda: RX._postar("http://10.208.0.9/x", "a", "b", "<x/>"),
    lambda: RX._colocar("http://10.208.0.9/x", "a", "b", "<x/>"),
    lambda: SL.conferir_senha("10.208.0.9", "a", "b"),
    lambda: AC._get({"host": "10.208.0.9", "username": "a", "password": "b"}, "/x"),
    lambda: AC._post_json({"host": "10.208.0.9", "username": "a", "password": "b"}, "/x", {}, "teste"),
])
def test_quem_manda_senha_nao_segue_redirect(rede, web, pede):
    try:
        pede()
    except HTTPException:
        pass
    assert _todos_sem_seguir(web[0])


def test_request_with_auth_e_confirmar_nao_seguem_redirect(rede, web, monkeypatch):
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip, hint="": {"remote_connector_id": "conn-a"})
    M._request_with_auth("http://10.208.0.9/x", "a", "b")
    assert _todos_sem_seguir(web[0])
    web[0].clear()
    M.maintenance_change_ip_confirmar({"ip": "192.168.10.9", "new_ip": "192.168.10.20", "user": "a", "pass": "b"})
    assert _todos_sem_seguir(web[0])


# ------------------------------------------------------------------ 3. nome
def test_conferir_alcance_recusa_nome(rede):
    with pytest.raises(ValueError, match="sem nome"):
        RX.conferir_alcance("gravador.exemplo", "")


def test_controladora_com_nome_nao_conecta_e_nao_cadastra(rede, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        AC._base_url_direct({"host": "porta.exemplo"})
    assert exc.value.status_code == 400 and "sem nome" in exc.value.detail
    monkeypatch.setattr(AS, "ensure_access_control_schema", lambda: None)
    monkeypatch.setattr(AS.db_store, "_conn", lambda: pytest.fail("gravou"))
    for corpo in ({"host": "porta.exemplo"}, {"host": "porta.exemplo", "connector_id": "conn-a"}):
        with pytest.raises(ValueError, match="sem nome"):
            AS.save_device({"name": "porta", **corpo})


def test_controladora_com_porta_nao_e_tratada_como_nome(rede):
    assert AC._base_url_direct({"host": "10.208.0.9:8080"}) == "http://10.208.0.9:8080"


def _olt(host):
    return {"id": 7, "host": host, "username": "u", "password": "p", "connector_id": "", "active": True,
            "name": "OLT", "site": "", "model": "", "vendor": ""}


def test_olt_com_nome_da_400(rede, monkeypatch):
    monkeypatch.setattr(OR, "resolve_credentials", lambda i: _olt("olt.exemplo"))
    with pytest.raises(HTTPException) as exc:
        O._registered_request(OltOnuSignalRequest(olt_id=7))
    assert exc.value.status_code == 400


# ------------------------------------------------------------------- 4. OLT
@pytest.fixture
def snmp(rede, monkeypatch):
    feitos = []
    monkeypatch.setattr(D, "_finais", {})
    monkeypatch.setattr(OS, "_e_fiberhome", lambda o: True)
    monkeypatch.setattr(OS, "coletar_saude_fiberhome", lambda h, c: feitos.append(h) or {})
    monkeypatch.setattr("app.services.db_store.get_json_state", lambda k, d=None: {})
    monkeypatch.setattr("app.services.db_store.set_json_state", lambda k, v: None)
    return feitos


def test_snmp_nao_coleta_olt_em_destino_recusado(snmp, caplog):
    with caplog.at_level(logging.WARNING, logger=OS.logger.name):
        OS.coletar_saude_olts([{"id": 1, "host": "10.208.1.5"}, {"id": 2, "host": "127.0.0.1"}], "public")
    assert snmp == []
    assert sum("destino recusado" in r.getMessage() for r in caplog.records) == 2


def test_snmp_coleta_olt_do_cliente_pelo_virtual(snmp):
    OS.coletar_saude_olts([{"id": 1, "host": "192.168.10.3", "connector_id": "conn-a"}], "public")
    assert snmp == ["10.208.0.3"]


@pytest.mark.parametrize("corpo", [{"host": "10.208.1.5"}, {"host": "192.168.10.3"}, {"host": "olt.exemplo"},
                                   {"host": "10.99.0.3", "connector_id": "conn-a"},
                                   {"host": "192.168.10.3", "connector_id": "conn-b"}])
def test_cadastro_de_olt_recusa_destino_alheio(rede, monkeypatch, corpo):
    monkeypatch.setattr(OR, "_conn", lambda: pytest.fail("gravou"))
    monkeypatch.setattr(OR, "upsert_site", lambda s: {})
    with pytest.raises(ValueError):
        OR.save_olt({"name": "OLT", **corpo})


# -------------------------------------------------------- 5. defeitos menores
def test_origem_do_aviso_nao_mostra_a_propria_trava(monkeypatch):
    def _q(arq, nome):
        return traceback.FrameSummary(arq, 1, nome, lookup_line=False, line="")

    monkeypatch.setattr(traceback, "extract_stack", lambda limit=None: [
        _q("/app/app/services/x.py", "coletar"), _q("/app/app/core/saida.py", "_connect"),
        _q("/usr/lib/python/http/client.py", "connect"), _q("/app/app/core/saida.py", "_conferir"),
        _q("/app/app/core/saida.py", "_avisar"), _q("/app/app/core/saida.py", "_pilha_curta")])
    pilha, origem = S._pilha_curta()
    assert "saida.py" not in pilha and origem.startswith("x.py")


def test_thread_que_nao_abre_nao_sobe_para_o_connect(estado, monkeypatch):
    def _falha(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(S.threading.Thread, "start", _falha)
    S._recarga_em = 0.0
    S._talvez_recarregar()
    assert S._recarregando.acquire(blocking=False)
    S._recarregando.release()


def test_mapa_vazio_mantem_a_lista_anterior(estado, monkeypatch):
    assert S.recusar("192.168.10.9")
    monkeypatch.setattr(vnat, "_load_map", lambda: {})
    S.recarregar(com_nomes=False)
    assert S.recusar("192.168.10.9")
    token = _como("cliente-a")
    try:
        assert S.recusar("10.209.128.5")
    finally:
        TC.reset_current_tenant_slug(token)


def test_redirect_com_barra_invertida_nao_e_seguido(web):
    chamadas, respostas = web
    respostas.append(_R(302, "http://10.209.128.5\@10.208.0.9/x"))
    assert S.pedir_mesmo_host("get", "http://10.208.0.9/a", timeout=1).status_code == 302
    assert len(chamadas) == 1


def test_redirect_com_location_invalido_nao_estoura(web):
    chamadas, respostas = web
    respostas.append(_R(302, "http://[x/"))
    assert S.pedir_mesmo_host("get", "http://10.208.0.9/a", timeout=1).status_code == 302
    assert len(chamadas) == 1


def test_ipv4_mapeado_em_ipv6_conta_como_ipv4(estado):
    token = _como("cliente-a")
    try:
        assert S.recusar("10.209.128.5") == S.recusar("::ffff:10.209.128.5")
        assert S.recusar("::ffff:192.168.1.5") == S.recusar("192.168.1.5")
    finally:
        TC.reset_current_tenant_slug(token)


def test_conectores_ilegiveis_nao_tiram_a_faixa_do_proprio_cliente(estado, monkeypatch):
    antes = list(S._estado.virtuais)
    assert any(d for _r, d in antes)
    monkeypatch.setattr(cs, "_load_connectors", lambda: [])
    S.recarregar()
    assert list(S._estado.virtuais) == antes


def test_com_contexto_leva_o_cliente_para_a_thread():
    from concurrent.futures import ThreadPoolExecutor

    token = _como("cliente-a")
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            sem = list(pool.map(lambda _: TC.get_current_tenant_slug(), range(3)))
            com = list(pool.map(S.com_contexto(lambda _: TC.get_current_tenant_slug()), range(3)))
    finally:
        TC.reset_current_tenant_slug(token)
    assert com == ["cliente-a"] * 3 and sem != com
