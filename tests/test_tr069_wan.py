"""Modo de operacao da ONT: leitura dos servicos e planejamento dos passos.

Fixture: a Intelbras 140PoE ITBS4420775E da SIERRA (gerencia DHCP VLAN 7 +
bridge VLAN 500 em LAN1-4), sem senhas.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import tr069_wan as wan

FIX = Path(__file__).parent / "fixtures" / "tr069"
GER = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANIPConnection.1"
BRIDGE = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.2.WANIPConnection.1"
LANS = ["LAN1", "LAN2", "LAN3", "LAN4"]


@pytest.fixture()
def doc():
    return json.loads((FIX / "intelbras_140poe_tr098.json").read_text(encoding="utf-8"))


def _bridge_atual(**mudar):
    base = {"id": BRIDGE, "funcao": "cameras", "modo": "bridge", "vlan": 500, "portas": LANS}
    base.update(mudar)
    return base


def test_servicos_da_140poe(doc):
    s = {x["id"]: x for x in wan.servicos(doc)}
    assert s[GER]["gerencia"] and not s[GER]["editavel"] and s[GER]["vlan"] == 7 and s[GER]["modo"] == "dhcp"
    b = s[BRIDGE]
    assert not b["gerencia"] and b["editavel"] and b["perfil"] == "intelbras"
    assert (b["modo"], b["vlan"], b["prioridade"], b["portas"]) == ("bridge", 500, None, LANS)


def test_cenario_reconhecido(doc):
    c = wan.cenario_atual(wan.servicos(doc))
    assert c["chave"] == "cameras_bridge" and "500" in c["texto"]


def test_sem_mudanca_nao_gera_passo(doc):
    assert wan.planejar(doc, [_bridge_atual()])["passos"] == []


def test_tirar_uma_porta_so_edita_o_campo_de_portas(doc):
    plano = wan.planejar(doc, [_bridge_atual(portas=["LAN1", "LAN2", "LAN3"])])
    assert [p["op"] for p in plano["_passos"]] == ["editar"]
    assert plano["_passos"][0]["valores"] == [[BRIDGE + ".X_ITBS_LanInterface", "LAN1,LAN2,LAN3", "xsd:string"]]
    assert any("LAN4" in a for a in plano["avisos"])


def test_trocar_vlan_e_prioridade(doc):
    plano = wan.planejar(doc, [_bridge_atual(vlan=600, prioridade=5)])
    valores = {v[0].rsplit(".", 1)[1]: v[1] for v in plano["_passos"][0]["valores"]}
    assert valores == {"X_ITBS_VlanMuxID": 600, "X_ITBS_VlanMux8021p": 5}


def test_gerencia_nunca_entra_no_plano(doc):
    plano = wan.planejar(doc, [])
    assert [p["op"] for p in plano["_passos"]] == ["remover"]
    assert plano["_passos"][0]["objeto"] == "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.2"
    assert all(GER not in json.dumps(p) for p in plano["_passos"])


def test_vlan_da_gerencia_e_recusada(doc):
    with pytest.raises(wan.WanError, match="gerencia"):
        wan.planejar(doc, [_bridge_atual(vlan=7)])


def test_porta_em_dois_servicos_e_recusada(doc):
    with pytest.raises(wan.WanError, match="LAN1"):
        wan.planejar(doc, [_bridge_atual(portas=["LAN1", "LAN2"]),
                           {"funcao": "iptv", "modo": "bridge", "vlan": 1334, "portas": ["LAN1"]}])


def test_porta_inexistente_e_recusada(doc):
    with pytest.raises(wan.WanError, match="LAN9"):
        wan.planejar(doc, [_bridge_atual(portas=["LAN9"])])


def test_multisservico_edita_e_cria(doc):
    plano = wan.planejar(doc, [
        _bridge_atual(portas=["LAN1", "LAN2"]),
        {"funcao": "iptv", "modo": "bridge", "vlan": 1334, "portas": ["LAN3", "LAN4"], "mcast_vlan": 1334, "igmp": True},
    ])
    assert [p["op"] for p in plano["_passos"]] == ["editar", "criar"]
    novo = plano["_passos"][1]["servico"]
    assert (novo["vlan"], novo["portas"], novo["mcast_vlan"], novo["igmp"]) == (1334, ["LAN3", "LAN4"], 1334, True)


def test_trocar_bridge_por_pppoe_remove_e_cria(doc):
    plano = wan.planejar(doc, [{"id": BRIDGE, "funcao": "internet", "modo": "pppoe", "vlan": 1125,
                                "portas": LANS, "usuario": "cliente@provedor", "senha": "segredo"}])
    assert [p["op"] for p in plano["_passos"]] == ["remover", "criar"]
    assert "segredo" not in json.dumps(plano["passos"])   # a previa nunca mostra a senha


def test_pppoe_sem_usuario_e_recusado(doc):
    with pytest.raises(wan.WanError, match="usuario"):
        wan.planejar(doc, [{"funcao": "internet", "modo": "pppoe", "vlan": 1125, "portas": LANS}])


def test_valores_de_servico_novo_intelbras():
    s = {"id_destino": "X.WANIPConnection.1", "modo": "bridge", "vlan": 500, "prioridade": None, "portas": ["LAN1"],
         "nat": False, "mcast_vlan": None, "igmp": False, "nome": "SightOps Cameras", "usuario": "", "senha": ""}
    v = {x[0].rsplit(".", 1)[1]: x[1] for x in wan._valores(s, wan.PERFIS["intelbras"], novo=True)}
    assert v["ConnectionType"] == "IP_Bridged" and v["X_ITBS_VlanMuxID"] == 500 and v["X_ITBS_VlanEnable"] is True
    assert v["X_ITBS_VlanMux8021p"] == -1 and v["X_ITBS_LanInterface"] == "LAN1" and v["X_RTK_ServiceType"] == 1
    assert v["Enable"] is True and v["Name"] == "SightOps Cameras"


def test_sem_gerencia_identificada_nada_e_alterado(doc):
    doc["InternetGatewayDevice"]["ManagementServer"]["ConnectionRequestURL"]["_value"] = "http://10.9.9.9:7547/"
    with pytest.raises(wan.WanError, match="gerencia"):
        wan.planejar(doc, [_bridge_atual()])
