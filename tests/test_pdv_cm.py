"""Caixa sem Espiao: o CM vira eventos no formato do Espiao (pdv_cm), o processador
usa uma fonte so por dia e o coletor manda so as linhas uteis do CM.

Fixture sintetica (tests/fixtures/pdv/CM271026.001) no formato real do CM, sem
nome nem documento real. A conferencia com dia real (PDV1 VITAL, 26/10 e 29/10:
mesmos cupons, itens, totais, pagamentos e bipado/digitado que o Espiao) foi
feita fora do repositorio, que e publico.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import time

import pytest

from app.services import pdv_cm
from app.services.pdv_processador import ProcessadorDia

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(RAIZ, "tests", "fixtures", "pdv")
DIA = "2026-10-27"
_spec = importlib.util.spec_from_file_location(
    "coletor_cm", os.path.join(RAIZ, "app", "services", "assets", "pdv_coletor", "sightops_pdv_coletor.py"))
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def _linhas(nome):
    with open(os.path.join(FIX, nome), "rb") as f:
        return [(i, b.rstrip(b"\r\n").decode("latin-1")) for i, b in enumerate(f, 1)]


CM = _linhas("CM271026.001")
CM_UTIL = [(s, pdv_cm.compactar(t)) for s, t in CM if pdv_cm.util(t)]


def _eventos():
    return [t for _, t in pdv_cm.converter(CM_UTIL)]


def test_cm_vira_linhas_de_espiao():
    ev = _eventos()
    assert "08:01:05:ABRECUPOM | Cod: 1001 | Descricao: Operador 01|" in ev
    assert ("08:01:13:VIT | Cod: 0000000011723 | Descricao: PAO FRANCES KG | Quant: 0.778 | Und: Kg | "
            "VlUnit: 11.99 | VlTotal: 9.33 | Desc2: 2117230009333|") in ev
    assert "08:01:22:DIT | Cod: 7896215300065 | Descricao: LEITE DE COCO 500ML | Und: Un | VlUnit: 0.28|" in ev
    assert "08:01:50:FIN | Cod: 1 | Descricao: DINHEIRO | VlUnit: 28.23 | VlTotal: 30|" in ev
    assert "08:01:50:TRC | Cod: 01 | Descricao: DINHEIRO | VlTotal: 1.77|" in ev
    # cartao recusado nao vira pagamento; o PIX aprovado vira, com Cod 99 como no Espiao
    fins = [e for e in ev if ":FIN " in e]
    assert fins == ["08:01:50:FIN | Cod: 1 | Descricao: DINHEIRO | VlUnit: 28.23 | VlTotal: 30|",
                    "08:03:45:FIN | Cod: 99 | Descricao: PIX | VlUnit: 5.4 | VlTotal: 5.4|"]
    assert "08:05:13:CCV | Cod: 1003 | Descricao: Operador 01 | VlTotal: 18.9|" in ev
    assert "08:10:02:SGR | Cod: 9001 | Descricao: Dinheiro | VlTotal: 40|" in ev
    assert "08:05:05:ITEMSEMCAD | Cod: 0000000003145|" in ev
    assert ev[-1] == "08:20:05:SOP | Cod: 9001 | Descricao: Operador 01|"
    # so um subtotal por tecla de subtotal (o caixa le o subtotal varias vezes)
    assert sum(1 for e in ev if ":SBT " in e and "1001" in e) == 1


def test_cupons_montados_pelo_cm():
    pr = ProcessadorDia(DIA)
    s = pr.receber(cm=CM_UTIL, final=True)
    cupons = {c["cupom"]: c for c in s["cupons"]}
    assert cupons["1001"]["situacao"] == "fechado"
    assert (cupons["1001"]["itens"], cupons["1001"]["itens_cancelados"]) == (3, 1)
    assert cupons["1001"]["total_centavos"] == 2823
    assert cupons["1001"]["pagamento"] == "DINHEIRO"
    assert cupons["1002"]["pagamento"] == "PIX"
    assert cupons["1003"]["situacao"] == "cancelado"
    assert pr.fonte == "cm"
    assert len({e["seq"] for e in s["eventos"]}) == len(s["eventos"])  # seq unico por evento


def test_cm_cortado_nao_derruba_e_lotes_picados_dao_o_mesmo():
    inteiro = ProcessadorDia(DIA).receber(cm=CM_UTIL, final=True)
    pr = ProcessadorDia(DIA)
    eventos = []
    for i in range(0, len(CM_UTIL), 3):
        eventos += pr.receber(cm=CM_UTIL[i:i + 3])["eventos"]
    eventos += pr.receber(cm=CM_UTIL, final=True)["eventos"]  # reenvio: nada duplica
    assert [e["seq"] for e in eventos] == [e["seq"] for e in inteiro["eventos"]]
    assert pdv_cm.ConversorCM().linha("08:00:00.000:COMANDO ==> (REGISTRA ITEM)  PARAMETRO()  /  TOTAIS COO: 1") == []
    assert pdv_cm.ConversorCM().linha("lixo sem hora") == []


def test_uma_fonte_por_dia():
    esp = [(1, "08:30:00:ABRECUPOM | Cod: 2001 | Descricao: Operador 01|"),
           (2, "08:30:01:VIT | Cod: 1 | Descricao: X | Quant: 1 | Und: Un | VlUnit: 1 | VlTotal: 1|")]
    pr = ProcessadorDia(DIA)
    pr.receber(cm=CM_UTIL, final=True)
    s = pr.receber(espiao=esp, final=True)  # ligaram o Espiao no meio do dia: ignora
    assert s["eventos"] == [] and pr.fonte == "cm"
    pr = ProcessadorDia(DIA)
    pr.receber(espiao=esp, final=True)
    assert pr.receber(cm=CM_UTIL, final=True)["eventos"] == [] and pr.fonte == "espiao"


def test_coletor_e_servidor_filtram_igual():
    assert tuple(C.MARCADORES_CM) == tuple(pdv_cm.MARCADORES)
    for _, t in CM:
        assert C.linha_cm(t) == (pdv_cm.compactar(t) if pdv_cm.util(t) else None)
    from app.services import pdv_store as S
    assert max(len(t) for _, t in CM_UTIL) < S.MAX_TAM_LINHA
    assert any(t.startswith("08:01:13.000:INSERT INTO venda VALUES ('VIT'") for _, t in CM_UTIL)


# ---------------------------------------------------------------- coletor no caixa sem Espiao

class _Servidor(object):
    def __init__(self):
        self.linhas = {}

    def __call__(self, payload):
        aceito = {}
        for l in payload["lotes"]:
            for seq, texto in l["linhas"]:
                self.linhas[(l["arquivo"], l["dia"], seq)] = texto
            aceito["%s/%s" % (l["arquivo"], l["dia"])] = l["linhas"][-1][0]
        return {"ok": True, "aceito": aceito}

    def arquivo(self, tipo, dia=DIA):
        return [self.linhas[k] for k in sorted(k for k in self.linhas if k[0] == tipo and k[1] == dia)]


@pytest.fixture()
def caixa(tmp_path):
    pasta = tmp_path / "Cm"
    pasta.mkdir()
    agora = {"t": dt.datetime(2026, 10, 27, 10, 0, 0)}
    srv = _Servidor()
    col = C.Coletor({"pasta": str(pasta), "estacao": 1}, estado_path=str(tmp_path / "estado.json"),
                    enviar=srv, relogio=lambda: agora["t"])
    col.gerador = False  # caixa sem o gerador do Espiao (ele tem teste proprio)
    return pasta, agora, srv, col


def _bytes_cm():
    with open(os.path.join(FIX, "CM271026.001"), "rb") as f:
        return f.read()


def test_coletor_le_o_cm_quando_nao_ha_espiao(caixa):
    pasta, agora, srv, col = caixa
    (pasta / "CM271026.001").write_bytes(_bytes_cm())
    col.ciclo()
    assert srv.arquivo("CM") == [t for _, t in CM_UTIL]
    assert srv.arquivo("Espiao") == []
    # so linha descartada depois: a posicao anda sem nada a confirmar
    with open(pasta / "CM271026.001", "ab") as f:
        f.write(b"10:00:01.000:TSqliteRP.LerTabela:Refresh(venda)|\r\n" * 50)
    col.ciclo()
    assert col.estado["CM271026.001"]["offset"] == os.path.getsize(pasta / "CM271026.001")
    # ligaram o Espiao no meio do dia: o coletor fica no CM ate o fim do dia
    (pasta / "Espiao271026.001").write_bytes(b"10:05:00:GAV|\r\n")
    col.ciclo()
    assert srv.arquivo("Espiao") == []


def test_coletor_na_virada_espera_o_espiao_nascer(caixa):
    pasta, agora, srv, col = caixa
    agora["t"] = dt.datetime(2026, 10, 27, 0, 0, 30)
    (pasta / "CM271026.001").write_bytes(b"00:00:01.000:COMANDO ==> (DATAJORNADA)  PARAMETRO()\r\n")
    col.ciclo()
    assert srv.arquivo("CM") == []  # cedo: o Espiao ainda pode aparecer
    (pasta / "Espiao271026.001").write_bytes(b"00:00:40:GAV|\r\n")
    agora["t"] = dt.datetime(2026, 10, 27, 0, 3, 0)
    col.ciclo()
    assert srv.arquivo("Espiao") == ["00:00:40:GAV|"] and srv.arquivo("CM") == []


def test_cm_ate_o_banco(tmp_path, monkeypatch):
    """Ponta a ponta pelo pdv_store, com a API reiniciando no meio do dia."""
    from app.core import tenant_context
    from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
    from app.services import db_store
    from app.services import pdv_store as S

    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    db_store.init_db()
    S._estado.clear()
    monkeypatch.setattr(S, "gravadores_do_cliente", lambda: {"192.168.24.227"})
    tok = set_current_tenant_slug("mercado-a")
    try:
        c = S.salvar_caixa({"nome": "PDV 03", "numero": 3, "gravador_host": "192.168.24.227", "gravador_canal": 3})
        cx = S.autenticar(c["id"], c["token"])
        meio = len(CM_UTIL) // 2
        t0 = time.time()  # a reconstrucao depois do reinicio usa o relogio de verdade
        r = S.receber_lote(cx, {"versao": "t", "lotes": [{"arquivo": "CM", "dia": DIA,
                                                           "linhas": [list(x) for x in CM_UTIL[:meio]]}]}, agora=t0)
        assert r["aceito"] == {"CM/%s" % DIA: CM_UTIL[meio - 1][0]}
        S._estado.clear()  # API reiniciou
        S.receber_lote(cx, {"versao": "t", "lotes": [{"arquivo": "CM", "dia": DIA,
                                                       "linhas": [list(x) for x in CM_UTIL[meio:]]}]}, agora=t0 + 1)
        S.receber_lote(cx, {"versao": "t", "lotes": []}, agora=t0 + 60)
        cupons = {k["cupom"]: k for k in S.buscar_cupons(DIA)}
        assert cupons["1001"]["total_centavos"] == 2823 and cupons["1001"]["situacao"] == "fechado"
        assert cupons["1003"]["situacao"] == "cancelado"
        antes = {k: (v["itens"], v["total_centavos"], v["situacao"]) for k, v in cupons.items()}
        S.reprocessar_dia(cx["id"], DIA)
        depois = {k["cupom"]: (k["itens"], k["total_centavos"], k["situacao"]) for k in S.buscar_cupons(DIA)}
        assert antes == depois
    finally:
        reset_current_tenant_slug(tok)
        S._estado.clear()


def test_coletor_espera_o_gerador_criar_o_espiao(caixa):
    pasta, agora, srv, col = caixa
    col.gerador = True  # instalados juntos: o coletor liga antes do Espiao gerado existir
    (pasta / "CM271026.001").write_bytes(_bytes_cm())
    col.ciclo()
    assert srv.arquivo("CM") == []
    (pasta / "Espiao271026.001").write_bytes(b"00:00:00---------- SightOps ----------\r\n10:00:00:GAV|\r\n")
    col.ciclo()
    assert srv.arquivo("Espiao")[-1] == "10:00:00:GAV|" and srv.arquivo("CM") == []
    col2 = C.Coletor({"pasta": str(pasta), "estacao": 2}, enviar=srv, relogio=lambda: agora["t"],
                     estado_path=str(pasta.parent / "e2.json"))
    col2.gerador, col2.inicio = True, col2.inicio - C.ESPERA_GERADOR - 1  # gerador nao criou: cai no CM
    (pasta / "CM271026.002").write_bytes(_bytes_cm())
    col2.ciclo()
    assert srv.arquivo("CM") != []


def test_insert_cortado_no_meio_ainda_traz_a_descricao():
    """Caso real do PDV-03: o corte de TAM_VALUES caia dentro do 'dados' e o nome sumia."""
    dados = "|7896013104919|Vinagre De Alcool Minhoto Lv750ml Pg500m|389|1000|389|0|030|0|N" + "|0" * 200
    linha = ("15:22:47.399:TVenda.GravaItem.cmdSql(1): INSERT INTO venda (tipo, status, st_canc, caixa, cupom, ope, "
             "data, dados) VALUES ('VIT', 'P', 'N', '003', '162902', '0181', '291026152247:291026152247', '%s', 1);|" % dados)
    curta = pdv_cm.compactar(linha)
    assert len(curta) < 400 and curta.count("'") % 2 == 1  # cortou dentro do texto
    cv = pdv_cm.ConversorCM()
    cv.linha(curta)
    out = cv.linha("15:22:47.406:COMANDO ==> (REGISTRA ITEM)  PARAMETRO()  /  TOTAIS COO: 162902  (SB: 0 / PG: 0 / "
                   "DC: 0 / AC: 0)  /  REGISTRA ITEM: 7896013104919  (VL: 3.89 / QT: 1 / TT: 3.89)")
    assert any("Descricao: Vinagre De Alcool Minhoto Lv750ml Pg500m" in l for l in out)
