"""Parsers da FiberHome AN5516 contra saidas REAIS da OLT da SIERRA.

As fixtures foram capturadas em 06/10/2026 (placa GC8B no slot 4, firmware
antigo). Se um firmware novo mudar o formato, o teste quebra aqui -- e nao
em producao, com a tela mostrando ONU vazia.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.cli.tools import olt_fiberhome as fh

FIX = Path(__file__).parent / "fixtures" / "fiberhome_an5516"


def _f(nome: str) -> str:
    return (FIX / f"{nome}.txt").read_text(encoding="utf-8")


def test_layout_acha_a_placa_gpon_do_slot_4():
    lay = fh.parse_layout(_f("device_show_slot"))
    assert lay.slots == (4,)
    assert lay.pons_per_slot == 8


def test_autorizacao_le_todas_as_onus_da_pon_3():
    onus = fh.parse_authorization(_f("auth_4_3"))
    assert len(onus) == 38
    por_id = {o["onu_id"]: o for o in onus}
    assert por_id[94]["onu_serial"] == "VSOL00C088E1"
    assert por_id[93]["onu_serial_raw"] == "ITBS44c87587"   # caixa exata p/ a whitelist
    assert por_id[94]["slot"] == 4 and por_id[94]["pon"] == 3


def test_online_casa_com_o_cabecalho():
    online = fh.parse_online(_f("online_4_3"), 4, 3)
    assert len(online) == 25
    assert {o["onu_id"] for o in online} >= {93, 94}


def test_versao_da_o_modelo_real():
    versoes = fh.parse_versions(_f("onuver_4_6"))
    # Cadastrada como HG260, e uma Intelbras PON140PoE: o REAL_TYPE e o que vale.
    assert versoes.get(89)


def test_pon_mac_liga_mac_a_onu_e_vlan():
    macs = fh.parse_pon_macs(_f("ponmac_4_3"))
    por_mac = {m["cpe_mac"]: m for m in macs}
    assert por_mac["58:10:8c:3d:44:81"]["onu_id"] == 94
    assert por_mac["58:10:8c:3d:44:81"]["vlan"] == "500"
    assert por_mac["54:6c:ac:16:6e:1e"]["onu_id"] == 93


def test_sinal_e_olt_rx_zerado_vira_vazio():
    sinal = fh.parse_signal(_f("optic_4_3_94"))
    assert sinal["onu_rx"] == "-25.22"
    assert fh._dbm(sinal["olt_rx"]) == ""        # 0.00 = sem medida nessa OLT
    assert fh._dbm(sinal["onu_rx"]) == "-25.22"


def test_distancia_em_km():
    assert fh.parse_distance(_f("rtt_4_3_94")) == "0.317"


def test_ultima_queda_sem_registro_fica_vazia():
    hist = fh.parse_last_on_off(_f("lastonoff_4_3_94"))
    assert hist["last_off_at"] == ""              # 0000-00-00 nao e data
    assert hist["last_on_at"] == "2009-03-12 01:29:27"


def test_descoberta_sem_onu_pendente():
    pons = fh.parse_discovery(_f("unauth_discovery"))
    assert pons                                   # um bloco por PON
    assert all(not b["discovered"] for b in pons.values())


def test_alvos_aceita_numero_e_slot_barra_pon():
    lay = fh.FiberHomeLayout(slots=(4,))
    assert fh._alvos(lay, "all")[0] == (4, 1) and len(fh._alvos(lay, "all")) == 8
    assert fh._alvos(lay, "3") == [(4, 3)]
    assert fh._alvos(lay, "4/3") == [(4, 3)]
    with pytest.raises(ValueError):
        fh._alvos(lay, "9")


def test_alvos_com_duas_placas_exige_slot():
    lay = fh.FiberHomeLayout(slots=(4, 5))
    with pytest.raises(ValueError):
        fh._alvos(lay, "3")
    assert fh._alvos(lay, "5/3") == [(5, 3)]
    assert fh._pon_label(lay, 5, 3) == "5/3"
    assert fh._pon_label(fh.FiberHomeLayout(slots=(4,)), 4, 3) == "3"
