"""ACL de acesso web da ONU: faixa calculada da propria ONU, regras SightOps proprias."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import tr069_acl as acl

FIX = Path(__file__).parent / "fixtures" / "tr069"


@pytest.fixture()
def doc():
    """140PoE da SIERRA com a regra 3 de WAN como vem de fabrica (0.0.0.0, desligada),
    igual a lida na ONU 3/17 da Easy -- a fixture so tem a regra 2 carregada."""
    import copy

    d = json.loads((FIX / "intelbras_140poe_tr098.json").read_text(encoding="utf-8"))
    regras = d["InternetGatewayDevice"]["X_ITBS_Acl"]["AclServices"]
    tres = copy.deepcopy(regras["2"])
    tres["MinSrcIp"]["_value"] = tres["MaxSrcIp"]["_value"] = "0.0.0.0"
    for k in ("HTTPWanEnable", "PINGWanEnable"):
        tres[k]["_value"] = False
    regras["3"] = tres
    return d


def test_faixa_sai_da_propria_onu(doc, monkeypatch):
    monkeypatch.setenv("SIGHTOPS_ACS_IP_ORIGEM", "10.10.12.7")
    # 140PoE da SIERRA: gerencia 172.18.1.254/24
    assert acl.faixas_desejadas(doc) == {"SightOps-gerencia": ("172.18.1.1", "172.18.1.254")}


def test_faixa_da_vlan_7_da_easy(doc):
    w = doc["InternetGatewayDevice"]["WANDevice"]["1"]["WANConnectionDevice"]["1"]["WANIPConnection"]["1"]
    w["ExternalIPAddress"]["_value"] = "10.7.0.13"
    w["SubnetMask"]["_value"] = "255.255.252.0"
    doc["InternetGatewayDevice"]["ManagementServer"]["ConnectionRequestURL"]["_value"] = "http://10.7.0.13:7547/tr069"
    assert acl.faixas_desejadas(doc)["SightOps-gerencia"] == ("10.7.0.1", "10.7.3.254")


def test_usa_as_regras_de_wan_que_a_onu_ja_tem(doc):
    assert [n for n, _ in acl.regras_wan(doc)] == [2, 3]   # a 1 e de LAN e fica de fora


def test_plano_so_mexe_na_regra_2_com_a_gerencia(doc):
    passos = acl.plano(doc)
    assert [(p["regra"], p["nome"]) for p in passos] == [(2, "SightOps-gerencia")]
    assert not any(".AclServices.1." in json.dumps(p) or ".AclServices.3." in json.dumps(p) for p in passos)


def test_regra_ja_certa_nao_gera_passo(doc, monkeypatch):
    monkeypatch.setenv("SIGHTOPS_ACS_IP_ORIGEM", "10.10.12.7")
    regras = doc["InternetGatewayDevice"]["X_ITBS_Acl"]["AclServices"]
    for n, (ini, fim) in ((2, ("172.18.1.1", "172.18.1.254")),):
        r = regras[str(n)]
        r["MinSrcIp"]["_value"], r["MaxSrcIp"]["_value"] = ini, fim
        for k, v in (("HTTPWanEnable", True), ("PINGWanEnable", True)):
            if k in r:
                r[k]["_value"] = v
    assert acl.plano(doc) == []
    regras["2"]["MaxSrcIp"]["_value"] = "172.18.1.100"
    passo = acl.plano(doc)
    assert [p["regra"] for p in passo] == [2]
    assert passo[0]["valores"] == [["InternetGatewayDevice.X_ITBS_Acl.AclServices.2.MaxSrcIp", "172.18.1.254", "xsd:string"]]


def test_nunca_mexe_em_https_telnet_ftp(doc):
    # a 140PoE recusa (cwmp 9003): o SightOps so mexe em faixa, HTTP e ping
    regra = doc["InternetGatewayDevice"]["X_ITBS_Acl"]["AclServices"]["2"]
    regra["TELNETWanEnable"]["_value"] = True
    nomes = {x[0].rsplit(".", 1)[1] for x in acl._valores_regra("X", regra, "1.1.1.1", "1.1.1.2")}
    assert nomes <= {"MinSrcIp", "MaxSrcIp", "HTTPWanEnable", "PINGWanEnable"}


def test_onu_sem_acl_intelbras_fica_de_fora(doc):
    doc["InternetGatewayDevice"].pop("X_ITBS_Acl")
    assert acl.plano(doc) == []
