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


# --- escrita: o fabricante do serial decide onde vai a VLAN ----------------
# Lido nas 160 ONUs da SIERRA (06/10/2026): so Intelbras roteador usa VEIP;
# "HG260" e so o tipo da whitelist e cobre Huawei/TP-Link/ZTE, todas por porta.

@pytest.mark.parametrize("modelo,serial,esperado", [
    ("HG260", "ITBS4420776c", "veip"),         # Intelbras PON140 (4/2/5, 4/6/89)
    ("HG260", "HWTCFF2D7D9D", "porta"),        # Huawei: 49 assim na SIERRA
    ("HG260", "TPLG12345678", "porta"),
    ("AN5506-01-A1", "ITBS00000001", "porta"),  # Intelbras bridge
    ("AN5506-04-A1", "FHTT074AB278", "porta"),
])
def test_modo_servico(modelo, serial, esperado):
    assert fh._modo_servico(modelo, serial) == esperado


def test_comandos_veip_um_indice_por_vlan():
    # Sequencia aplicada e conferida na HG260 4/2/5 da SIERRA.
    cmds = fh._comandos_servico(4, 2, 5, "veip", "HG260",
                                [{"vlan": 7, "service": "management"},
                                 {"vlan": 500, "service": "downlink"}])
    assert cmds == [
        "set epon slot 4 pon 2 onu 5 port 1 onuveip 1 33024 7 65535 33024 65535 65535 33024 65535 65535 0 1 65535 servn null",
        "set epon slot 4 pon 2 onu 5 port 1 onuveip 2 33024 500 65535 33024 65535 65535 33024 65535 65535 0 1 65535 servn null",
        "apply onu 4 2 5 vlan",
    ]


def test_veip_recusa_tv_nao_homologada():
    with pytest.raises(ValueError):
        fh._comandos_servico(4, 2, 5, "veip", "HG260", [{"vlan": 1334, "service": "iptv"}])


def test_comandos_porta_uma_vlan_em_todas_as_portas():
    cmds = fh._comandos_servico(4, 3, 9, "porta", "AN5506-04-F1", [{"vlan": 500, "service": "tls"}])
    assert "set epon slot 4 pon 3 onu 9 port 4 service number 1" in cmds
    assert "set epon slot 4 pon 3 onu 9 port 1 service 1 vlan_mode transparent 0 33024 500" in cmds
    assert cmds[-1] == "apply onu 4 3 9 vlan"
    assert len(cmds) == 4 * 2 + 1


def test_tv_vira_par_unicast_multicast_na_porta():
    # Mesmo desenho das ONUs de TV da SIERRA (ex.: 4/7/89): internet na 1, TV na 2.
    cmds = fh._comandos_servico(4, 7, 89, "porta", "AN5506-04-A1",
                                [{"vlan": 1125, "service": "downlink"},
                                 {"vlan": 1334, "service": "iptv"}])
    assert cmds == [
        "set epon slot 4 pon 7 onu 89 port 1 service number 1",
        "set epon slot 4 pon 7 onu 89 port 1 service 1 vlan_mode tag 0 33024 1125",
        "set epon slot 4 pon 7 onu 89 port 2 service number 2",
        "set epon slot 4 pon 7 onu 89 port 2 service 1 vlan_mode tag 0 33024 1334",
        "set epon slot 4 pon 7 onu 89 port 2 service 2 vlan_mode tag 0 33024 1334",
        "set epon slot 4 pon 7 onu 89 port 2 service 2 type multicast",
        "apply onu 4 7 89 vlan",
    ]


def test_porta_escolhida_na_tela_vence_a_ordem():
    por_porta = fh._servicos_por_porta("AN5506-04-A1", [
        {"vlan": 1125, "service": "downlink", "port": 1},
        {"vlan": 1334, "service": "iptv", "port": 4},
    ])
    assert por_porta == {1: [("tag", 1125, "unica")],
                         4: [("tag", 1334, "unica"), ("tag", 1334, "multi")]}
    with pytest.raises(ValueError):
        fh._servicos_por_porta("AN5506-01-A1", [{"vlan": 1, "service": "downlink", "port": 2}])


def test_parse_servicos_porta_real_com_tv():
    assert fh.parse_servicos_porta(_f("onuservice_4_2_15")) == [
        (1, 1, "unica", "tag", 1125),
        (2, 1, "unica", "tag", 1334),
        (2, 2, "multi", "tag", 1334),
        (3, 1, "unica", "tag", 640),
    ]


class _Falso:
    def __init__(self, saida):
        self.saida = saida

    def command(self, *_a, **_k):
        return self.saida


def test_conferir_pega_tv_sem_multicast():
    # 4/2/15 real: a TV da porta 2 esta completa; pedir TV na 3 acusa as duas linhas.
    cliente = _Falso(_f("onuservice_4_2_15"))
    pedidos = [{"vlan": 1125, "service": "downlink"}, {"vlan": 1334, "service": "iptv"}]
    assert fh._conferir_servico(cliente, 4, 2, 15, "porta", "AN5506-04-A1", pedidos) == []
    pedidos_3 = [{"vlan": 1125, "service": "downlink", "port": 1},
                 {"vlan": 1334, "service": "iptv", "port": 3}]
    assert fh._conferir_servico(cliente, 4, 2, 15, "porta", "AN5506-04-A1", pedidos_3) == [
        "porta 3 servico 1 (unica 1334)", "porta 3 servico 2 (multi 1334)"]


def test_ajuda_nunca_manda_enter():
    enviados = []

    class Sock:
        def sendall(self, dados):
            enviados.append(dados)

    c = fh.FiberHomeTelnet.__new__(fh.FiberHomeTelnet)
    c.sock = Sock()
    c._read_quiet = lambda maximum=0: ""
    c.ajuda("set epon slot 4 pon 7 onu 89 port 2 service 2 type")
    assert all(b"\r" not in d and b"\n" not in d for d in enviados)
    assert enviados[-1] == b"\x15"


def test_lista_de_online_vazia_ou_cortada_nao_vira_los():
    """OLT SIERRA, 15/10/2026: resposta vazia virou 106 ONUs em LOS."""
    import pytest
    with pytest.raises(fh.LeituraIncompleta):
        fh.parse_online("show online slot 4 link 1\r\nAdmin\\gpononu# ", 4, 1)
    cortada = _f("online_4_3").split(" 49 ")[0]          # 25 anunciadas, chegaram menos
    with pytest.raises(fh.LeituraIncompleta):
        fh.parse_online(cortada, 4, 3)
    assert fh.parse_online("ONLINE ONU TOTAL NUM = 0\r\nAdmin\\gpononu# ", 4, 1) == []   # ninguem online: LOS de verdade
    assert len(fh.parse_online(_f("online_4_6"), 4, 6)) == 42


def test_online_tenta_de_novo_antes_de_descartar():
    import pytest

    class Cli:
        host = "olt"
        def __init__(self, respostas): self.respostas = list(respostas)
    leitor = fh._Leitor(Cli([]))
    respostas = ["lixo sem cabecalho", _f("online_4_3")]
    leitor._cmd = lambda menu, cmd, maximum=30.0: respostas.pop(0)
    assert len(leitor.online(4, 3)) == 25                       # segunda veio inteira
    respostas[:] = ["lixo", "lixo de novo"]
    with pytest.raises(fh.LeituraIncompleta):
        leitor.online(4, 3)


def test_command_descarta_sobra_de_comando_anterior():
    """Sessao deslocada: a sobra do comando anterior chega antes da resposta."""
    cli = fh.FiberHomeTelnet.__new__(fh.FiberHomeTelnet)
    cli.host, cli.timeout = "olt", 5.0
    pedacos = ["show online slot 4 link 3\r\nONLINE ONU TOTAL NUM = 4\r\n 01 HG260 HWTC00000001 ,\r\nAdmin\gpononu# ",
               _f("online_4_6")]
    cli.send = lambda v: None
    cli._read_quiet = lambda quiet=0.45, maximum=None: pedacos.pop(0) if pedacos else ""
    out = cli.command("show online slot 4 link 6", prompt="Admin\gpononu#", maximum=3.0)
    assert out.startswith("show online slot 4 link 6") and len(fh.parse_online(out, 4, 6)) == 42


def test_command_sem_eco_volta_vazio_e_online_recusa():
    cli = fh.FiberHomeTelnet.__new__(fh.FiberHomeTelnet)
    cli.host, cli.timeout = "olt", 1.0
    cli.send = lambda v: None
    cli._read_quiet = lambda quiet=0.45, maximum=None: "show online slot 4 link 3\r\nONLINE ONU TOTAL NUM = 0\r\nAdmin\gpononu# "
    out = cli.command("show online slot 4 link 6", prompt="Admin\gpononu#", maximum=1.0)
    assert out == ""
    import pytest
    with pytest.raises(fh.LeituraIncompleta):
        fh.parse_online(out, 4, 6)


def test_onu_so_e_offline_se_faltar_nas_duas_leituras(monkeypatch):
    monkeypatch.setattr(fh.time, "sleep", lambda s: None)
    autorizadas = [{"onu_id": i, "onu_serial": f"S{i}", "onu_model": "HG260"} for i in (1, 2, 3)]
    leituras = [{1}, {1, 2}]                     # 1a leitura parcial; 2a traz a 2

    class L:
        def autorizadas(self, s, p): return autorizadas
        def online(self, s, p): return leituras.pop(0)
        def versoes(self, s, p): return {}
        def sinal(self, *a): return {}
        def distancia(self, *a): return ""
    rows = fh._onus_da_pon(L(), fh.FiberHomeLayout(slots=(4,)), 4, 6, com_sinal=False, com_distancia=False)
    assert {r["onu_id"]: r["oper_status"] for r in rows} == {1: "Active", 2: "Active", 3: "Offline"}
