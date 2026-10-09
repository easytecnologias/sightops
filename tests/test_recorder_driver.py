"""Driver de gravador: diagnostico, aplicacao com conferencia e indice.

Fixture: configuracao REAL do NVR Intelbras 10.10.9.120 (NVR4X-4KS2, firmware
4.000.00IB001.2) lida em 09/10/2026 antes da padronizacao -- canais 1, 2 e 16,
mais NTP. Canal 2 e 16 estavam com movimento desligado; o 16 tinha sensibilidade
ajustada a mao (84/26), que o driver nao pode tocar.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, unquote

import pytest

from app.services import recorder_driver as rd

FIX = Path(__file__).parent / "fixtures" / "gravador" / "intelbras_nvr4x_120.txt"


@pytest.fixture()
def pares():
    return rd._pares(FIX.read_text(encoding="utf-8"))


class GravadorFalso:
    """Imita o CGI da Intelbras, inclusive o defeito: setConfig so aplica a
    PRIMEIRA tabela do pedido e responde OK mesmo assim."""

    def __init__(self, pares, ignora=()):
        self.estado = dict(pares)
        self.ignora = set(ignora)
        self.pedidos = []

    def __call__(self, url):
        caminho = url.split("://", 1)[1].split("/", 1)[1]
        self.pedidos.append(caminho)
        if "action=getConfig" in caminho:
            nome = re.search(r"name=(\w+)", caminho).group(1)
            linhas = [f"table.{k}={v}" for k, v in self.estado.items() if rd._tabela(k) == nome]
            return 200, "\n".join(linhas)
        if "action=setConfig" in caminho:
            qs = [(unquote(k), v) for k, v in parse_qsl(caminho.split("?", 1)[1]) if k != "action"]
            primeira = rd._tabela(qs[0][0])
            for k, v in qs:
                if rd._tabela(k) == primeira and k not in self.ignora:
                    self.estado[k] = v
            return 200, "OK\r\n"
        if "getCurrentTime" in caminho:
            return 200, f"result={datetime.now():%Y-%m-%d %H:%M:%S}"
        return 404, ""


def _gravador(falso):
    return rd.Gravador("10.10.9.120", "admin", "x", 80, pedir=falso, marca="intelbras")


def test_diagnostico_do_120_real(pares):
    mud, alertas = rd.diagnosticar_intelbras(pares)
    por = {m.chave: m for m in mud}
    # canais 2 e 16 (indices 1 e 15) estavam desligados; o 1 ja estava ligado
    assert por["MotionDetect[1].Enable"].para == "true"
    assert por["MotionDetect[15].Enable"].para == "true"
    assert "MotionDetect[0].Enable" not in por
    # pre 4 -> 10 e pos 10 -> 30 nos tres canais
    assert {por[f"Record[{i}].PreRecord"].de for i in (0, 1, 15)} == {"4"}
    assert {por[f"MotionDetect[{i}].EventHandler.RecordLatch"].para for i in (0, 1, 15)} == {"30"}
    assert por["NTP.Enable"].para == "true"
    # ja era H.264 e tinha gravacao continua 24h: nada a trocar, nada a avisar
    assert not any("Compression" in m.chave for m in mud)
    assert alertas == []
    # sensibilidade ajustada a mao nunca entra
    assert not any("Sensitive" in m.chave or "Threshold" in m.chave for m in mud)
    assert len(mud) == 2 + 3 + 3 + 1


def test_valores_acima_do_perfil_ficam(pares):
    pares["Record[0].PreRecord"] = "20"
    pares["MotionDetect[0].EventHandler.RecordLatch"] = "60"
    mud, _ = rd.diagnosticar_intelbras(pares)
    chaves = {m.chave for m in mud}
    assert "Record[0].PreRecord" not in chaves
    assert "MotionDetect[0].EventHandler.RecordLatch" not in chaves


def test_codec_h265_vira_h264_e_avisa_retencao(pares):
    pares["Encode[1].MainFormat[0].Video.Compression"] = "H.265"
    pares["Encode[0].MainFormat[0].Video.Compression"] = "H.264H"  # e H.264, nao mexe
    mud, alertas = rd.diagnosticar_intelbras(pares)
    trocas = [m for m in mud if "Compression" in m.chave]
    assert [(m.chave, m.para) for m in trocas] == [("Encode[1].MainFormat[0].Video.Compression", "H.264")]
    assert any("retencao" in a for a in alertas)


def test_sem_gravacao_continua_so_avisa(pares):
    for faixa in range(6):
        pares[f"Record[1].TimeSection[3][{faixa}]"] = "2 00:00:00-24:00:00"  # so movimento na quarta
    mud, alertas = rd.diagnosticar_intelbras(pares)
    assert any("canais 2" in a for a in alertas)
    assert not any("TimeSection" in m.chave for m in mud)


def test_aplicar_uma_tabela_por_pedido_e_tudo_pega(pares):
    falso = GravadorFalso(pares)
    g = _gravador(falso)
    d = g.diagnostico()
    r = g.aplicar(d["mudancas"])
    assert r["ok"] and r["aplicadas"] == len(d["mudancas"]) and r["nao_pegaram"] == []
    for pedido in (p for p in falso.pedidos if "setConfig" in p):
        tabelas = {rd._tabela(unquote(k)) for k, _ in parse_qsl(pedido.split("?", 1)[1]) if k != "action"}
        assert len(tabelas) == 1, pedido
    assert falso.estado["NTP.Enable"] == "true"
    assert falso.estado["Record[15].PreRecord"] == "10"
    assert rd.diagnosticar_intelbras(falso.estado)[0] == []


def test_aplicar_denuncia_o_que_nao_pegou(pares, tmp_path):
    falso = GravadorFalso(pares, ignora={"NTP.Enable"})
    g = _gravador(falso)
    r = g.aplicar(g.diagnostico()["mudancas"], backup_dir=tmp_path)
    assert not r["ok"] and r["nao_pegaram"] == ["NTP.Enable"]
    backup = Path(r["backup"]).read_text(encoding="utf-8")
    assert "table.Record[0].PreRecord=4" in backup


def test_parse_indice_separa_movimento():
    texto = (
        "found=3\r\n"
        "items[0].StartTime=2026-10-09 10:45:00\r\nitems[0].EndTime=2026-10-09 10:50:00\r\n"
        "items[0].Flags[0]=Timing\r\nitems[0].Length=1000\r\n"
        "items[1].StartTime=2026-10-09 10:55:01\r\nitems[1].EndTime=2026-10-09 10:56:32\r\n"
        "items[1].Flags[0]=Event\r\nitems[1].Events[0]=VideoMotion\r\nitems[1].Length=500\r\n"
        "items[2].StartTime=2026-10-09 10:56:32\r\n"  # sem EndTime: descarta
    )
    segs = rd.parse_indice(texto)
    assert [(s.tipo, s.tamanho) for s in segs] == [("continuo", 1000), ("movimento", 500)]


def test_url_playback_por_marca():
    g = rd.Gravador("10.0.0.1", "admin", "a@b", 80, pedir=lambda u: (200, ""), marca="intelbras")
    ini, fim = datetime(2026, 10, 8, 15, 0, 0), datetime(2026, 10, 8, 15, 5, 0)
    assert g.url_playback(27, ini, fim).endswith(
        "@10.0.0.1:554/cam/playback?channel=27&starttime=2026_10_08_15_00_00&endtime=2026_10_08_15_05_00")
    assert "a%40b" in g.url_playback(27, ini, fim)
    g.marca = "hikvision"
    assert "/Streaming/tracks/101?starttime=20261008T150000Z" in g.url_playback(1, ini, fim)


def test_hikvision_nao_finge_padronizar():
    g = rd.Gravador("10.0.0.1", "admin", "x", 80, pedir=lambda u: (200, ""), marca="hikvision")
    with pytest.raises(rd.ErroDriver):
        g.diagnostico()
