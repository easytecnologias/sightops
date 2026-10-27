"""Ponto de venda: coletor -> banco -> consultas, com SQLite de verdade (tmp).

Dados da fixture sintetica (tests/fixtures/pdv): sem nome nem documento real.
"""
from __future__ import annotations

import os

import pytest

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import pdv_leitor as L
from app.services import pdv_store as S

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "pdv")
DIA = "2026-10-27"


def _linhas(nome):
    with open(os.path.join(FIX, nome), encoding="latin-1", newline="") as f:
        return [[i, l.rstrip("\r\n")] for i, l in enumerate(f, 1)]


ESP, TEC = _linhas("Espiao271026.001"), _linhas("Teclas271026.001")


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    from app.core import tenant_context
    from app.services import db_store

    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    db_store.init_db()
    S._estado.clear()
    monkeypatch.setattr(S, "gravadores_do_cliente", lambda: {"192.168.24.227"})
    tok = set_current_tenant_slug("mercado-a")
    yield
    reset_current_tenant_slug(tok)
    S._estado.clear()


def _caixa(nome="PDV 01"):
    return S.salvar_caixa({"nome": nome, "numero": 1, "gravador_host": "192.168.24.227", "gravador_canal": 1})


def _enviar(caixa, esp, tec, agora=1000.0):
    lotes = []
    if esp:
        lotes.append({"arquivo": "Espiao", "dia": DIA, "linhas": esp})
    if tec:
        lotes.append({"arquivo": "Teclas", "dia": DIA, "linhas": tec})
    return S.receber_lote(caixa, {"versao": "teste", "lotes": lotes}, agora=agora)


def _cupons():
    return {k["cupom"]: k for k in S.buscar_cupons(DIA)}


def test_token_so_volta_na_criacao_e_autentica(banco):
    cx = _caixa()
    assert cx["token"].startswith("pdv_") and cx["token_prefixo"] == cx["token"][:8]
    assert "token" not in S.listar_caixas()[0]
    assert S.autenticar(cx["id"], cx["token"])["tenant_slug"] == "mercado-a"
    assert S.autenticar(cx["id"], "pdv_errado") is None
    novo = S.novo_token(cx["id"])["token"]
    assert S.autenticar(cx["id"], cx["token"]) is None and S.autenticar(cx["id"], novo)


def test_dia_inteiro_igual_ao_leitor_da_fase_0(banco):
    caixa = S.autenticar(*(lambda c: (c["id"], c["token"]))(_caixa()))
    r = _enviar(caixa, ESP, TEC)
    assert r["aceito"] == {"Espiao/%s" % DIA: len(ESP), "Teclas/%s" % DIA: len(TEC)}
    S.receber_lote(caixa, {"lotes": []}, agora=10_000.0)  # o tempo passa: nada fica esperando
    ref = L.ler_dia(os.path.join(FIX, "Espiao271026.001"), os.path.join(FIX, "Teclas271026.001"))
    k = _cupons()
    assert set(k) == {"1001", "1002", "1003", "1004"}
    assert k["1001"]["situacao"] == "fechado" and k["1001"]["total_centavos"] == 3008
    assert (k["1001"]["bipados"], k["1001"]["digitados"], k["1001"]["menu"]) == (2, 1, 1)
    assert k["1001"]["itens_cancelados"] == 1 and k["1001"]["pagamento"] == "DINHEIRO"
    assert k["1002"]["situacao"] == "cancelado" and k["1004"]["situacao"] == "cancelado"
    assert k["1003"]["situacao"] == "fechado" and k["1003"]["pagamento"] == "PIX"
    resumo = S.resumo_dia(DIA)
    assert resumo["itens"] == len(ref.itens) == 9
    assert {m: v["n"] for m, v in resumo["modos"].items()} == {"scanner": 5, "manual": 1, "menu": 1, "sem_tecla": 1, "outro": 1}
    assert resumo["eventos"]["CIT"] == 1 and resumo["eventos"]["CCV"] == 2 and resumo["eventos"]["CCG"] == 1


def test_lotes_picados_e_reenvio_dao_o_mesmo(banco):
    c1 = _caixa("PDV 01")
    caixa = S.autenticar(c1["id"], c1["token"])
    # o coletor manda de 7 em 7 linhas, o Teclas atrasado um lote, e reenvia tudo no fim
    i = j = 0
    anterior = 0
    agora = 0.0
    while i < len(ESP) or j < len(TEC):
        _enviar(caixa, ESP[i:i + 7], TEC[anterior:j], agora=agora)  # Teclas: o lote anterior
        anterior = j
        i += 7
        j = min(len(TEC), j + 13)
        agora += 2
    _enviar(caixa, [], TEC[anterior:], agora=agora)
    _enviar(caixa, ESP, TEC, agora=agora)  # reenvio total: nada duplica
    _enviar(caixa, [], [], agora=agora + 100)
    picado = {c: (k["itens"], k["bipados"], k["total_centavos"], k["situacao"]) for c, k in _cupons().items()}
    S.reprocessar_dia(caixa["id"], DIA)
    inteiro = {c: (k["itens"], k["bipados"], k["total_centavos"], k["situacao"]) for c, k in _cupons().items()}
    assert picado == inteiro
    assert S.resumo_dia(DIA)["itens"] == 9


def test_api_reiniciou_no_meio_do_dia(banco):
    c1 = _caixa()
    caixa = S.autenticar(c1["id"], c1["token"])
    meio = len(ESP) // 2
    _enviar(caixa, ESP[:meio], TEC, agora=0.0)
    S._estado.clear()  # reiniciou: estado em memoria some
    _enviar(caixa, ESP[meio:], [], agora=100.0)
    _enviar(caixa, [], [], agora=1000.0)
    assert S.resumo_dia(DIA)["itens"] == 9
    assert _cupons()["1001"]["total_centavos"] == 3008


def test_cliente_nao_ve_caixa_de_outro(banco):
    c1 = _caixa()
    _enviar(S.autenticar(c1["id"], c1["token"]), ESP, TEC)
    tok = set_current_tenant_slug("mercado-b")
    try:
        assert S.listar_caixas() == [] and S.buscar_cupons(DIA) == []
        assert S.resumo_dia(DIA)["itens"] == 0
        with pytest.raises(ValueError):
            S.detalhe_cupom(c1["id"], DIA, "1001")
        with pytest.raises(ValueError):
            S.ao_vivo(c1["id"])
        with pytest.raises(ValueError):
            S.novo_token(c1["id"])
    finally:
        reset_current_tenant_slug(tok)


def test_detalhe_e_ao_vivo(banco):
    c1 = _caixa()
    _enviar(S.autenticar(c1["id"], c1["token"]), ESP, TEC, agora=10_000.0)
    d = S.detalhe_cupom(c1["id"], DIA, "1001")
    assert [i["modo"] for i in d["itens"]] == ["scanner", "scanner", "manual", "menu", "sem_tecla", "outro"]
    tipos = [e["tipo"] for e in d["linha_do_tempo"]]
    assert tipos[0] == "ABRECUPOM" and "CIT" in tipos and tipos[-1] == "FECHACUPOM" and "NUM" not in tipos
    v = S.ao_vivo(c1["id"])
    assert v["cupom"]["cupom"] == "1004" and v["itens"][0]["descricao"] == "WHISKY 1L"


def test_busca_por_produto_e_situacao(banco):
    c1 = _caixa()
    _enviar(S.autenticar(c1["id"], c1["token"]), ESP, TEC, agora=10_000.0)
    assert [k["cupom"] for k in S.buscar_cupons(DIA, texto="whisky")] == ["1004"]
    assert {k["cupom"] for k in S.buscar_cupons(DIA, situacao="cancelado")} == {"1002", "1004"}
    assert [k["cupom"] for k in S.buscar_cupons(DIA, situacao="item_cancelado")] == ["1001"]
    assert [k["cupom"] for k in S.buscar_cupons(DIA, texto="1003")] == ["1003"]


def test_lote_invalido(banco):
    c1 = _caixa()
    caixa = S.autenticar(c1["id"], c1["token"])
    for ruim in ({"lotes": [{"arquivo": "CM", "dia": DIA, "linhas": []}]},
                 {"lotes": [{"arquivo": "Espiao", "dia": "27/10/2026", "linhas": []}]},
                 {"lotes": [{"arquivo": "Espiao", "dia": DIA, "linhas": [[0, "x"]]}]},
                 {"lotes": "x"}):
        with pytest.raises(ValueError):
            S.receber_lote(caixa, ruim)


def test_rota_do_coletor_e_publica_e_a_de_caixa_e_de_admin():
    from fastapi import FastAPI

    from app.core.security import ApiAuthMiddleware
    from app.core.settings import get_settings
    m = ApiAuthMiddleware(FastAPI(), get_settings())
    assert m._is_public_path("/api/pdv/coletor/lote")
    assert not m._is_public_path("/api/pdv/caixas")
    assert m._match_role_rule("/api/pdv/caixas", "POST") == "admin"
    assert m._match_role_rule("/api/pdv/caixas/abc/token", "POST") == "admin"


def test_video_no_relogio_do_gravador(banco, monkeypatch):
    c1 = _caixa()
    caixa = S.autenticar(c1["id"], c1["token"])
    j = S.janela_video(c1["id"], "2026-10-27 15:12:04", antes=10, depois=30)
    assert (j["host"], j["canal"], j["relogio_medido"]) == ("192.168.24.227", 1, False)
    assert (j["inicio"], j["fim"]) == ("2026-10-27 15:11:54", "2026-10-27 15:12:34")
    # caixa 2 s adiantado em relacao ao servidor; gravador 6 s adiantado -> gravador = caixa + 4
    import datetime as dt
    agora = dt.datetime.now()
    S.receber_lote(caixa, {"relogio": (agora + dt.timedelta(seconds=2)).strftime("%Y-%m-%d %H:%M:%S"), "lotes": []})
    pdv_off = S.listar_caixas()[0]["relogio_pdv_offset_s"]
    assert pdv_off in (1, 2, 3)  # 2 s, com folga para a virada de segundo
    dif = S.registrar_relogio_dvr(c1["id"], 6)["gravador_menos_caixa_s"]
    assert dif == 6 - pdv_off
    j = S.janela_video(c1["id"], "2026-10-27 15:12:00", antes=0, depois=10)
    assert j["momento_gravador"] == "2026-10-27 15:12:%02d" % dif and j["relogio_medido"] is True
    sem = S.salvar_caixa({"nome": "PDV 02", "numero": 2})
    with pytest.raises(ValueError):
        S.janela_video(sem["id"], "2026-10-27 15:12:04")


def test_caixa_vira_entidade_de_monitoramento(banco):
    import datetime as dt
    c1 = _caixa()
    S.salvar_caixa({"nome": "PDV 09", "numero": 9, "ativo": 0})
    e = {x["display_name"]: x for x in S.entidades_monitoramento()}
    assert e["PDV 01"]["status"] == "unknown" and e["PDV 09"]["status"] == "maintenance"
    S.receber_lote(S.autenticar(c1["id"], c1["token"]), {"lotes": [{"arquivo": "Espiao", "dia": DIA, "linhas": ESP}]})
    agora = dt.datetime.now(dt.timezone.utc)
    e = {x["display_name"]: x for x in S.entidades_monitoramento(agora)}
    assert e["PDV 01"]["status"] == "online" and e["PDV 01"]["entity_key"] == "pdv:" + c1["id"]
    assert e["PDV 01"]["detail"]["contato_s"] <= 5
    e = {x["display_name"]: x for x in S.entidades_monitoramento(agora + dt.timedelta(minutes=10))}
    assert e["PDV 01"]["status"] == "offline"


def test_gravador_tem_que_ser_do_inventario_do_cliente(banco):
    with pytest.raises(ValueError):
        S.salvar_caixa({"nome": "PDV 05", "numero": 5, "gravador_host": "10.0.0.99", "gravador_canal": 1})
    assert S.salvar_caixa({"nome": "PDV 05", "numero": 5, "gravador_host": "192.168.24.227", "gravador_canal": 5})["id"]
