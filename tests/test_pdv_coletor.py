"""Coletor do caixa (tools/pdv/coletor): le os arquivos do PDV aos poucos e entrega
ao servidor sem perder nem duplicar linha. Fixture sintetica, sem dado real."""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import urllib.error

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(RAIZ, "tests", "fixtures", "pdv")
_spec = importlib.util.spec_from_file_location(
    "coletor", os.path.join(RAIZ, "tools", "pdv", "coletor", "sightops_pdv_coletor.py"))
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def _bytes(nome):
    with open(os.path.join(FIX, nome), "rb") as f:
        return f.read()


ESP, TEC = _bytes("Espiao271026.001"), _bytes("Teclas271026.001")


class Servidor(object):
    """Guarda as linhas por (arquivo, dia, seq), como o banco; pode cair."""

    def __init__(self):
        self.linhas = {}
        self.fora_do_ar = False
        self.chamadas = 0

    def __call__(self, payload):
        self.chamadas += 1
        if self.fora_do_ar:
            raise urllib.error.URLError("sem rede")
        aceito = {}
        for l in payload["lotes"]:
            for seq, texto in l["linhas"]:
                self.linhas[(l["arquivo"], l["dia"], seq)] = texto
            aceito["%s/%s" % (l["arquivo"], l["dia"])] = l["linhas"][-1][0]
        return {"ok": True, "aceito": aceito}

    def arquivo(self, tipo, dia):
        seqs = sorted(s for (a, d, s) in self.linhas if a == tipo and d == dia)
        assert seqs == list(range(1, len(seqs) + 1)), "buraco ou repeticao de seq"
        return [self.linhas[(tipo, dia, s)] for s in seqs]


def _texto(b):
    return [l.rstrip("\r") for l in b.decode("latin-1").split("\n") if l != ""]


@pytest.fixture()
def amb(tmp_path):
    pasta = tmp_path / "Cm"
    pasta.mkdir()
    agora = {"t": dt.datetime(2026, 10, 27, 10, 0, 0)}
    srv = Servidor()
    col = C.Coletor({"pasta": str(pasta), "estacao": 1}, estado_path=str(tmp_path / "estado.json"),
                    enviar=srv, relogio=lambda: agora["t"])
    return pasta, agora, srv, col


def test_le_aos_poucos_e_segura_linha_pela_metade(amb):
    pasta, agora, srv, col = amb
    corte = ESP.index(b"\n", len(ESP) // 2) + 5  # no meio de uma linha
    (pasta / "Espiao271026.001").write_bytes(ESP[:corte])
    (pasta / "Teclas271026.001").write_bytes(TEC)
    col.ciclo()
    meio = srv.arquivo("Espiao", "2026-10-27")
    assert meio == _texto(ESP[:ESP.rindex(b"\n", 0, corte)])  # a linha cortada nao foi
    (pasta / "Espiao271026.001").write_bytes(ESP)
    col.ciclo()
    assert srv.arquivo("Espiao", "2026-10-27") == _texto(ESP)
    assert srv.arquivo("Teclas", "2026-10-27") == _texto(TEC)


def test_sem_rede_nao_perde_nem_duplica(amb):
    pasta, agora, srv, col = amb
    (pasta / "Espiao271026.001").write_bytes(ESP[:500])
    col.ciclo()
    srv.fora_do_ar = True
    (pasta / "Espiao271026.001").write_bytes(ESP)
    assert col.ciclo() == -1 and col.espera > C.INTERVALO
    srv.fora_do_ar = False
    col.ciclo()
    assert srv.arquivo("Espiao", "2026-10-27") == _texto(ESP)


def test_posicao_sobrevive_a_reinicio(amb, tmp_path):
    pasta, agora, srv, col = amb
    (pasta / "Espiao271026.001").write_bytes(ESP)
    col.ciclo()
    antes = dict(srv.linhas)
    novo = C.Coletor({"pasta": str(pasta), "estacao": 1}, estado_path=str(tmp_path / "estado.json"),
                     enviar=srv, relogio=lambda: agora["t"])
    assert novo.ciclo() == 0  # so o sinal de vida: nenhuma linha reenviada
    assert srv.linhas == antes


def test_meia_noite_termina_o_de_ontem_e_segue_o_de_hoje(amb):
    pasta, agora, srv, col = amb
    agora["t"] = dt.datetime(2026, 10, 27, 23, 59, 50)
    (pasta / "Espiao271026.001").write_bytes(ESP[:800])
    col.ciclo()
    # virou o dia; o PDV ainda escreveu o fim do arquivo de ontem, SEM \n na ultima linha
    agora["t"] = dt.datetime(2026, 10, 28, 0, 0, 30)
    (pasta / "Espiao271026.001").write_bytes(ESP.rstrip(b"\r\n"))
    (pasta / "Espiao281026.001").write_bytes(ESP[:300])
    col.ciclo()
    assert srv.arquivo("Espiao", "2026-10-27") == _texto(ESP)[:-1]  # ultima ainda pode crescer
    agora["t"] = dt.datetime(2026, 10, 28, 0, 15, 0)  # passou FECHAR_APOS: encerra ontem
    col.ciclo()
    col.ciclo()
    assert srv.arquivo("Espiao", "2026-10-27") == _texto(ESP)
    assert col.estado["Espiao271026.001"]["fim"] is True
    assert srv.arquivo("Espiao", "2026-10-28") == _texto(ESP[:ESP.rindex(b"\n", 0, 300)])


def test_coletor_ate_o_banco(amb, tmp_path, monkeypatch):
    """Ponta a ponta: arquivo do caixa -> coletor -> pdv_store -> cupons."""
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
    tok = set_current_tenant_slug("mercado-a")
    try:
        cx = S.salvar_caixa({"nome": "PDV 01", "numero": 1})
        caixa = S.autenticar(cx["id"], cx["token"])
        pasta, agora, _, _ = amb
        col = C.Coletor({"pasta": str(pasta), "estacao": 1}, estado_path=str(tmp_path / "e2.json"),
                        enviar=lambda p: S.receber_lote(caixa, p, agora=10_000.0), relogio=lambda: agora["t"])
        for parte in (0.3, 0.6, 1.0):
            (pasta / "Espiao271026.001").write_bytes(ESP[:int(len(ESP) * parte)])
            (pasta / "Teclas271026.001").write_bytes(TEC[:int(len(TEC) * parte)])
            col.ciclo()
        assert S.resumo_dia("2026-10-27")["itens"] == 9
        assert {k["cupom"] for k in S.buscar_cupons("2026-10-27")} == {"1001", "1002", "1003", "1004"}
        assert S.listar_caixas()[0]["coletor_versao"] == C.VERSAO
    finally:
        reset_current_tenant_slug(tok)
        S._estado.clear()
