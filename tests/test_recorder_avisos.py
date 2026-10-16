"""Avisos e correcoes do gravador, sobre a configuracao REAL do NVR 10.10.9.120
(mesma fixture de test_recorder_driver). O gravador falso imita o CGI da
Intelbras, inclusive o setConfig que so aplica a primeira tabela."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.services import recorder_avisos as ra
from app.services import recorder_driver as rd
from test_recorder_driver import FIX, GravadorFalso


@pytest.fixture()
def pares():
    return rd._pares(FIX.read_text(encoding="utf-8"))


class GravadorComRelogio(GravadorFalso):
    def __init__(self, pares, atraso_s=0, **kw):
        super().__init__(pares, **kw)
        self.atraso = timedelta(seconds=atraso_s)

    def __call__(self, url):
        caminho = url.split("://", 1)[1].split("/", 1)[1]
        if "getCurrentTime" in caminho:
            self.pedidos.append(caminho)
            return 200, f"result={datetime.now() + self.atraso:%Y-%m-%d %H:%M:%S}"
        if "setCurrentTime" in caminho:
            self.pedidos.append(caminho)
            self.atraso = timedelta(0)
            return 200, "OK"
        return super().__call__(url)


def _g(falso):
    return rd.Gravador("10.10.9.120", "admin", "x", 80, pedir=falso, marca="intelbras")


def test_avisos_do_120_real(pares):
    avisos = {a["id"]: a for a in ra.montar_avisos(pares)}
    # canais 2 e 16 sem movimento; pre/pos curtas em 1, 2, 16; NTP desligado
    assert avisos["movimento"]["titulo"].startswith("2 canal")
    assert "02, 16" in avisos["movimento"]["lido"]
    assert "01–02, 16" in avisos["pre_pos"]["lido"]
    assert avisos["ntp"]["nivel"] == "erro" and avisos["ntp"]["seguro"]
    # ja tinha gravacao continua e H.264: nada a avisar
    assert "continua" not in avisos and "codec" not in avisos
    # o navegador recebe a mudanca descrita, nunca o lote interno
    pub = ra._publico(avisos["movimento"])
    assert "_mudancas" not in pub


def test_corrigir_rele_aplica_e_registra(pares, tmp_path):
    falso = GravadorComRelogio(pares)
    r = ra.corrigir(_g(falso), "movimento", tmp_path, por="elishafan")
    assert r["ok"] and r["aplicadas"] == 2
    assert falso.estado["MotionDetect[15].Enable"] == "true"
    # so o movimento: NTP e pre/pos continuam como estavam
    assert falso.estado["NTP.Enable"] != "true"
    assert falso.estado["Record[0].PreRecord"] == "4"
    reg = ra.ler_registro(tmp_path, r["registro"])
    assert reg["por"] == "elishafan" and reg["host"] == "10.10.9.120" and reg["desfazivel"]
    # segunda vez: ja estava, nada escrito
    antes = len([p for p in falso.pedidos if "setConfig" in p])
    r2 = ra.corrigir(_g(falso), "movimento", tmp_path)
    assert r2.get("ja_estava") and len([p for p in falso.pedidos if "setConfig" in p]) == antes


def test_desfazer_volta_os_valores_de_antes(pares, tmp_path):
    falso = GravadorComRelogio(pares)
    original = dict(falso.estado)
    r = ra.corrigir(_g(falso), "pre_pos", tmp_path)
    assert falso.estado["Record[0].PreRecord"] == "10"
    d = ra.desfazer(_g(falso), r["registro"], tmp_path, por="x")
    assert d["ok"]
    for k in ("Record[0].PreRecord", "MotionDetect[0].EventHandler.RecordLatch"):
        assert falso.estado[k] == original[k]
    assert ra.ler_registro(tmp_path, r["registro"])["desfeito_em"]
    # registro de um gravador nao desfaz em outro
    outro = rd.Gravador("10.10.9.121", "admin", "x", 80, pedir=falso, marca="intelbras")
    with pytest.raises(rd.ErroDriver):
        ra.desfazer(outro, r["registro"], tmp_path)


def test_mesmo_ip_atras_de_outro_conector_nao_mistura(pares, tmp_path):
    falso = GravadorComRelogio(pares)
    r = ra.corrigir(_g(falso), "pre_pos", tmp_path, conector="site-a")
    assert "backup" not in r
    assert [x["id"] for x in ra.registros_do_host(tmp_path, "10.10.9.120", conector="site-a")] == [r["registro"]]
    assert ra.registros_do_host(tmp_path, "10.10.9.120", conector="site-b") == []
    assert "backup" not in ra.registros_do_host(tmp_path, "10.10.9.120", conector="site-a")[0]
    with pytest.raises(rd.ErroDriver):
        ra.desfazer(_g(falso), r["registro"], tmp_path, conector="site-b")
    assert ra.desfazer(_g(falso), r["registro"], tmp_path, conector="site-a")["ok"]


def test_relogio_adiantado_vira_aviso_e_acerta(pares, tmp_path):
    falso = GravadorComRelogio(pares, atraso_s=252)
    avisos = {a["id"]: a for a in ra.avisos_do_gravador(_g(falso))["avisos"]}
    t = avisos["relogio"]["titulo"]
    assert t.startswith("Relógio 4 min 1") and t.endswith("adiantado")
    r = ra.corrigir(_g(falso), "relogio", tmp_path)
    assert r["ok"] and any("setCurrentTime" in p for p in falso.pedidos)
    assert not ra.ler_registro(tmp_path, r["registro"])["desfazivel"]


def test_relogio_em_dia_nao_avisa(pares):
    falso = GravadorComRelogio(pares, atraso_s=20)
    ids = {a["id"] for a in ra.avisos_do_gravador(_g(falso))["avisos"]}
    assert "relogio" not in ids


def test_sem_continua_soma_o_bit_e_nao_e_seguro(pares, tmp_path):
    for dia in range(7):
        for faixa in range(6):
            pares[f"Record[1].TimeSection[{dia}][{faixa}]"] = "0 00:00:00-00:00:00"
        pares[f"Record[1].TimeSection[{dia}][0]"] = "2 08:00:00-18:00:00"
    avisos = {a["id"]: a for a in ra.montar_avisos(pares)}
    a = avisos["continua"]
    assert not a["seguro"] and "retenção" in a["alerta"] and "02" in a["lido"]
    assert {m["para"] for m in a["_mudancas"]} == {"3 00:00:00-24:00:00"}
    falso = GravadorComRelogio(pares)
    assert ra.corrigir(_g(falso), "continua", tmp_path)["ok"]
    assert "continua" not in {x["id"] for x in ra.montar_avisos(falso.estado)}


def test_faixas():
    assert ra._faixas([1, 2, 3, 5, 9, 10]) == "01–03, 05, 09–10"


def test_hikvision_so_mostra_relogio_sem_corrigir(pares, tmp_path):
    falso = GravadorComRelogio(pares)
    g = rd.Gravador("10.0.0.9", "admin", "x", 80, pedir=falso, marca="hikvision")
    with pytest.raises(rd.ErroDriver):
        ra.corrigir(g, "movimento", tmp_path)
