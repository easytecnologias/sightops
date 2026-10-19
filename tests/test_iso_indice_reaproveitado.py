"""Indice de tunel reaproveitado nao pode herdar peer nem rota do conector anterior.

Caso real, 19/10/2026: o INCOFORTE (novo, grupo-jangadeiros) recebeu o indice 1.
O wgc1 ja existia desde a v2 com o peer do PORTO REAL DO COLEGIO (apagado), e
`wg set peer` so acrescenta: o tunel do cliente novo ficou com 2 peers e com
192.168.10.0/24, 10.45.0.0/24 e 10.250.0.2 na tabela 1001.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "iso_provisioner_reaproveitado", RAIZ / "deploy" / "iso-provisioner" / "iso_provisioner.py")
prov = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prov)

NOVO = "uyF5YsT962A/gPLiZCEVAmDohK4V9q4gCiCD/W74vDk="
VELHO = "VURW8XB1OEVfOEWIQEpxLMpgFj0/+sMvpfqgjwzno0o="

TABELA_1001 = """\
10.45.0.0/24 dev wgc1 scope link
10.201.0.0/24 dev wgc1 scope link
10.201.0.3 dev wgc1 scope link
10.250.0.2 dev wgc1 scope link
172.16.15.0/24 dev wgc1 scope link
192.168.10.0/24 dev wgc1 scope link
192.168.20.0/23 dev wgc1 scope link
"""
LANS = ["10.201.0.0/24", "172.16.15.0/24", "192.168.20.0/23"]


def test_peer_do_conector_anterior_sai():
    assert prov.peers_sobrando(f"{VELHO}\n{NOVO}\n", NOVO) == [VELHO]


def test_so_o_peer_certo_nao_sobra_nada():
    assert prov.peers_sobrando(f"{NOVO}\n", NOVO) == []


def test_rotas_do_conector_anterior_saem():
    sobra = prov.rotas_sobrando(TABELA_1001, "wgc1", ["10.201.0.3/32"] + LANS)
    assert sorted(sobra) == ["10.250.0.2/32", "10.45.0.0/24", "192.168.10.0/24"]


def test_rota_contida_numa_rede_do_conector_fica():
    # SIERRA: tabela 1013 com 10.200.1.0/24 e o conector com 10.200.0.0/23.
    tabela = "10.200.1.0/24 dev wgc13 scope link\n10.201.0.27 dev wgc13 scope link\n"
    assert prov.rotas_sobrando(tabela, "wgc13", ["10.201.0.27/32", "10.200.0.0/23"]) == []


def test_rota_de_outra_interface_nao_e_tocada():
    tabela = "192.168.10.0/24 dev wg-sightops scope link\n"
    assert prov.rotas_sobrando(tabela, "wgc1", ["10.201.0.3/32"]) == []
