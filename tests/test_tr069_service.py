"""TR-069: leitura do modelo de dados, dono da ONU e chamada pelo conector.

A fixture e o documento REAL da Intelbras 140PoE ITBS4420775E da SIERRA,
tirado do GenieACS em 07/10/2026, com todos os valores de senha removidos.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services import tr069_service as tr

FIX = Path(__file__).parent / "fixtures" / "tr069"


@pytest.fixture()
def doc():
    return json.loads((FIX / "intelbras_140poe_tr098.json").read_text(encoding="utf-8"))


def test_fixture_nao_tem_senha(doc):
    """Todo parametro de senha/chave da fixture tem que estar REMOVIDO."""
    import re

    vazados = []

    def walk(o, chave=""):
        if isinstance(o, dict):
            if "_value" in o and re.search(r"pass|pswd|secret|psk|key", chave, re.I) and o["_value"] not in ("", None, "REMOVIDO"):
                vazados.append(chave)
            for k, v in o.items():
                walk(v, k)
    walk(doc)
    assert vazados == []
    assert tr._v(doc, "InternetGatewayDevice.ManagementServer.ConnectionRequestPassword") == "REMOVIDO"


@pytest.mark.parametrize("entrada,esperado", [
    ("HWTCDC390F9A", "HWTCDC390F9A"),
    ("hwtc-dc390f9a", "HWTCDC390F9A"),
    ("48575443DC390F9A", "HWTCDC390F9A"),   # fabricante em hex, como varios CPEs informam
    ("ITBS4420775E", "ITBS4420775E"),
    ("0123456789ABCDEF", "0123456789ABCDEF"),  # hex que nao e letra de fabricante: fica como esta
])
def test_normalizar_serial(entrada, esperado):
    assert tr.normalizar_serial(entrada) == esperado


def test_formas_do_serial_inclui_hex():
    assert tr._formas_do_serial("HWTCDC390F9A") == ["48575443DC390F9A", "HWTCDC390F9A"]


def test_resumo_tr098_da_140poe(doc):
    r = tr.resumo_do_dispositivo(doc)
    assert r["padrao"] == "tr098"
    assert r["serial"] == "ITBS4420775E"
    assert r["modelo"] == "140PoE"
    assert r["firmware"] == "2.2-230830"
    assert [p["porta"] for p in r["lan"]] == [1, 2, 3, 4]
    assert all(p["habilitada"] for p in r["lan"])
    wan = r["wan"][0]
    assert wan["tipo"] == "ip" and wan["status"] == "Connected" and wan["ip"] == "172.18.1.254"
    assert wan["vlan"] == 7 and wan["prioridade"] == 7   # gerencia: VlanMuxID 7, 802.1p 7
    bridge = r["wan"][1]
    assert bridge["modo"] == "IP_Bridged" and bridge["vlan"] == 500 and bridge["prioridade"] is None
    assert bridge["portas"] == "LAN1,LAN2,LAN3,LAN4"
    assert r["wifi"] == []           # 140PoE nao tem radio
    assert r["intervalo_s"] == 300


def test_estado_pelo_ultimo_contato(doc):
    r = tr.resumo_do_dispositivo(doc)
    visto = datetime.fromisoformat(r["ultimo_contato"].replace("Z", "+00:00")).timestamp()
    assert tr.estado(r, agora=visto + 60) == "gerenciada"
    assert tr.estado(r, agora=visto + 2 * 300 + 61) == "sem_contato"
    assert tr.estado({"ultimo_contato": None}) == "aguardando"


def test_porta_lan_vira_set_parameter(doc):
    r = tr.resumo_do_dispositivo(doc)
    tarefa, desc = tr._tarefa("porta_lan", r, {"porta": 2, "habilitar": False})
    assert tarefa == {"name": "setParameterValues", "parameterValues": [
        ["InternetGatewayDevice.LANDevice.1.LANEthernetInterfaceConfig.2.Enable", False, "xsd:boolean"]]}
    assert desc == "Desligar LAN 2"
    with pytest.raises(tr.Tr069Error):
        tr._tarefa("porta_lan", r, {"porta": 9})


def test_reset_de_fabrica_exige_serial(doc):
    r = tr.resumo_do_dispositivo(doc)
    with pytest.raises(tr.Tr069Error):
        tr._tarefa("reset_fabrica", r, {})
    assert tr._tarefa("reset_fabrica", r, {"confirmar_serial": "itbs4420775e"})[0] == {"name": "factoryReset"}


def test_wifi_recusado_sem_radio(doc):
    with pytest.raises(tr.Tr069Error):
        tr._tarefa("wifi", tr.resumo_do_dispositivo(doc), {"indice": 1, "ssid": "X"})


class _VnatFalso:
    IP_BLOQUEADO = "240.0.0.1"

    def __init__(self, mapa, do_cliente=True):
        self.mapa, self.do_cliente = mapa, do_cliente

    def virtual_ip_for(self, cid, ip):
        if self.mapa and not self.do_cliente:
            return self.IP_BLOQUEADO
        return self.mapa.get(ip, ip)

    def has_mapping(self, cid):
        return bool(self.mapa)


@pytest.fixture()
def vnat(monkeypatch):
    import app.services as pacote

    def instalar(falso):
        monkeypatch.setattr(pacote, "connector_routing_vnat", falso, raising=False)
        import sys
        monkeypatch.setitem(sys.modules, "app.services.connector_routing_vnat", falso)
    return instalar


def test_chamada_vai_pelo_ip_virtual(doc, vnat):
    vnat(_VnatFalso({"172.18.1.254": "10.211.5.254"}))
    assert tr._url_de_chamada(doc, "1d634b442abbac6c") == "http://10.211.5.254:7547/tr069"


def test_chamada_bloqueada_para_conector_de_outro_cliente(doc, vnat):
    vnat(_VnatFalso({"172.18.1.254": "10.211.5.254"}, do_cliente=False))
    assert tr._url_de_chamada(doc, "conector-alheio") is None


def test_chamada_bloqueada_fora_das_faixas_do_conector(doc, vnat):
    # O conector tem mapa, mas nao para 172.18.1.0/24: o IP real cairia na rota
    # principal do servidor, que pode ser a rede de outro cliente.
    vnat(_VnatFalso({"10.200.0.1": "10.211.2.1"}))
    assert tr._url_de_chamada(doc, "1d634b442abbac6c") is None


def test_expressao_cwmp_auth():
    expr = tr.expressao_cwmp_auth([("sierra", "abc123"), ("rads", "Xyz9")], aceitar_legada=True)
    assert expr == 'AUTH("sierra", "abc123") OR AUTH("rads", "Xyz9") OR AUTH("acs", "acs")'
    assert tr.expressao_cwmp_auth([], aceitar_legada=False) == "false"
    with pytest.raises(tr.Tr069Error):
        tr.expressao_cwmp_auth([("sierra", 'a" OR true OR "b')], aceitar_legada=False)


def test_lista_so_mostra_onu_do_cliente(doc, monkeypatch):
    linha_onu = {"onu_serial": "ITBS4420775E", "olt_name": "OLT SIERRA", "pon_label": "4/6", "onu_id": 89,
                 "connector_id": "1d634b442abbac6c", "rx_onu": "-21.4", "oper_status": "Active"}
    monkeypatch.setattr(tr, "onus_do_cliente", lambda: {"ITBS4420775E": linha_onu, "HWTCDC390F9A": {}})
    pedidos = []

    def nbi(method, path, params=None, body=None, timeout=10.0):
        pedidos.append(json.loads(params["query"]))
        return [doc]
    monkeypatch.setattr(tr, "_nbi", nbi)
    monkeypatch.setattr(tr, "get_config_publica", lambda: {"aguardando": {}})
    out = tr.listar()
    # a busca no GenieACS vai SO com os seriais deste cliente
    assert set(pedidos[0]["_deviceId._SerialNumber"]["$in"]) == {
        "ITBS4420775E", "495442534420775E", "HWTCDC390F9A", "48575443DC390F9A"}
    assert [o["serial"] for o in out["onus"]] == ["ITBS4420775E"]
    assert out["contagem"]["sem_tr069"] == 1
    assert out["onus"][0]["wan"]["vlan"] == 7


def test_detalhe_de_serial_alheio_nao_confirma_existencia(monkeypatch):
    monkeypatch.setattr(tr, "onus_do_cliente", lambda: {})
    with pytest.raises(tr.Tr069Error, match="nao encontrada neste cliente"):
        tr.detalhe("ITBS4420775E")


def test_gravar_config_sem_login_configurado(monkeypatch):
    monkeypatch.delenv("SIGHTOPS_ACS_UI_USER", raising=False)
    monkeypatch.delenv("SIGHTOPS_ACS_UI_PASSWORD", raising=False)
    with pytest.raises(tr.Tr069Error, match="login do SightOps"):
        tr._gravar_config("cwmp.auth", "false")


def test_gravar_config_confere_lendo_de_volta(monkeypatch):
    monkeypatch.setenv("SIGHTOPS_ACS_UI_USER", "sightops")
    monkeypatch.setenv("SIGHTOPS_ACS_UI_PASSWORD", "x")
    chamadas = []

    class Resp:
        def __init__(self, code):
            self.status_code, self.text = code, ""

    class Sessao:
        def post(self, url, json=None, timeout=None):
            chamadas.append(("POST", url, json))
            return Resp(200)

        def put(self, url, json=None, timeout=None):
            chamadas.append(("PUT", url, json))
            return Resp(200)
    monkeypatch.setattr(tr.requests, "Session", Sessao)
    monkeypatch.setattr(tr, "_nbi", lambda *a, **k: [{"_id": "cwmp.auth", "value": "outra coisa"}])
    with pytest.raises(tr.Tr069Error, match="nao ficou gravado"):
        tr._gravar_config("cwmp.auth", 'AUTH("a", "b")')
    assert chamadas[1] == ("PUT", "http://genieacs:3000/api/config/cwmp.auth", {"value": 'AUTH("a", "b")'})
    monkeypatch.setattr(tr, "_nbi", lambda *a, **k: [{"_id": "cwmp.auth", "value": 'AUTH("a", "b")'}])
    tr._gravar_config("cwmp.auth", 'AUTH("a", "b")')


def test_documento_completo_nao_manda_projection_vazio(doc, monkeypatch):
    params_vistos = []
    monkeypatch.setattr(tr, "onus_do_cliente", lambda: {"ITBS4420775E": {"connector_id": "x"}})
    monkeypatch.setattr(tr, "_nbi", lambda m, p, params=None, body=None, timeout=10.0: params_vistos.append(params) or [doc])
    tr._documento_do_cliente("ITBS4420775E")
    assert "projection" not in params_vistos[0]


def test_serial_curto_da_8820i_casa_com_o_completo():
    onus = {"F1D35486": {}, "ITBS4420775E": {}}
    assert tr.serial_do_inventario("ITBSF1D35486", onus) == "F1D35486"
    assert tr.serial_do_inventario("ITBS4420775E", onus) == "ITBS4420775E"
    assert tr.serial_do_inventario("ZZZZ00000000", onus) == "ZZZZ00000000"


def test_busca_de_serial_curto_vai_por_regex(monkeypatch):
    pedidos = []
    monkeypatch.setattr(tr, "_nbi", lambda m, p, params=None, body=None, timeout=10.0: pedidos.append(json.loads(params["query"])) or [])
    tr._buscar_por_seriais(["F1D35486", "ITBS4420775E"], "_id")
    assert {"_deviceId._SerialNumber": {"$in": ["495442534420775E", "ITBS4420775E"]}} in pedidos
    assert {"_deviceId._SerialNumber": {"$regex": "^([A-Za-z]{4})?(F1D35486)$"}} in pedidos


def test_rede_direta_chama_sem_tunel(doc, monkeypatch, vnat):
    vnat(_VnatFalso({"10.200.0.1": "10.211.2.1"}))  # conector com mapa, sem a rede da ONU
    doc["InternetGatewayDevice"]["ManagementServer"]["ConnectionRequestURL"]["_value"] = "http://10.7.0.13:7547/tr069"
    monkeypatch.setattr(tr, "redes_diretas", lambda: [])
    assert tr._url_de_chamada(doc, "7a53c66a4e5dcae0") is None
    monkeypatch.setattr(tr, "redes_diretas", lambda: ["10.7.0.0/22"])
    assert tr._url_de_chamada(doc, "7a53c66a4e5dcae0") == "http://10.7.0.13:7547/tr069"


def test_redes_diretas_so_privadas_e_de_tamanho_razoavel(monkeypatch):
    monkeypatch.setattr(tr, "garantir_credencial", lambda: {})
    import app.services.db_store as db
    monkeypatch.setattr(db, "set_json_state", lambda k, v: None)
    assert tr.salvar_redes_diretas(["10.7.0.0/22"]) == ["10.7.0.0/22"]
    for ruim in ("8.8.8.0/24", "10.0.0.0/8", "fe80::/64", "abc"):
        with pytest.raises(tr.Tr069Error):
            tr.salvar_redes_diretas([ruim])
