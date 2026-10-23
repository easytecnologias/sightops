"""Controle de Rotas: contratos, escolas, rotas com paradas e alunos (SQLite tmp).
So dados ficticios."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import rotas_cadastro as C
from app.services import rotas_store as R

HOJE = date.today()


def _d(dias: int) -> str:
    return (HOJE + timedelta(days=dias)).isoformat()


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    from app.core import tenant_context
    from app.services import db_store

    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    db_store.init_db()
    tok = set_current_tenant_slug("prefeitura-x")
    yield
    reset_current_tenant_slug(tok)


def _base():
    """Contrato vigente, escola, onibus de 3 lugares e motorista liberados."""
    op = R.salvar_operador({"nome": "Empresa A"})["id"]
    ctt = C.salvar_contratante({"nome": "Prefeitura Teste"})["id"]
    ct = C.salvar_contrato({"contratante_id": ctt, "operador_id": op, "numero": "12/2026",
                            "preco_km": "4,85", "inicio": _d(-30), "fim": _d(300)})["id"]
    esc = C.salvar_escola({"nome": "E.M. Centro", "inep": "12345678", "lat": "-10.1", "lon": "-36.8"})["id"]
    vei = R.salvar_veiculo({"operador_id": op, "placa": "ABC1D23", "lugares": "3",
                            "vistoria_validade": _d(200), "autorizacao_validade": _d(200), "seguro_validade": _d(200)})["id"]
    mot = R.salvar_motorista({"operador_id": op, "nome": "Motorista", "cnh_categoria": "D",
                              "cnh_validade": _d(500), "curso_validade": _d(500)})["id"]
    return {"op": op, "ctt": ctt, "ct": ct, "esc": esc, "vei": vei, "mot": mot}


def _paradas(n=2):
    return [{"nome": f"Parada {i}", "horario": f"06:{30 + i:02d}", "lat": -10.0 - i / 100, "lon": -36.8}
            for i in range(1, n + 1)]


def _rota(b, **extra):
    payload = {"nome": "Rota 07", "contrato_id": b["ct"], "escola_id": b["esc"], "veiculo_id": b["vei"],
               "motorista_id": b["mot"], "km_previsto": "27,9", "paradas": _paradas()}
    payload.update(extra)
    return C.salvar_rota(payload)["id"]


def _rota_lida(rid):
    return next(r for r in C.cadastro()["rotas"] if r["id"] == rid)


def test_rota_completa_liberada_e_preco_sem_perder_centavo(banco):
    b = _base()
    rid = _rota(b)
    r = _rota_lida(rid)
    assert r["situacao"] == "liberado", r["motivos"]
    assert [p["ordem"] for p in r["paradas"]] == [1, 2]
    assert r["km_previsto"] == 27.9
    ct = C.cadastro()["contratos"][0]
    assert ct["preco_km"] == "4.85" and ct["contratante_nome"] == "Prefeitura Teste" and ct["rotas"] == 1


def test_rota_bloqueada_pelo_que_falta(banco):
    b = _base()
    assert "Menos de 2 paradas" in _rota_lida(_rota(b, nome="R1", paradas=_paradas(1)))["motivos"]
    assert "Sem motorista" in _rota_lida(_rota(b, nome="R2", motorista_id=""))["motivos"]
    R.salvar_veiculo({"id": b["vei"], "operador_id": b["op"], "placa": "ABC1D23", "lugares": "3",
                      "vistoria_validade": _d(-1), "autorizacao_validade": _d(200)})
    r = _rota_lida(_rota(b, nome="R3"))
    assert r["situacao"] == "bloqueado" and "Veículo bloqueado" in r["motivos"]


def test_contrato_vencido_ou_que_nao_comecou_bloqueia(banco):
    b = _base()
    C.salvar_contrato({"id": b["ct"], "contratante_id": b["ctt"], "operador_id": b["op"], "fim": _d(-2)})
    assert "Contrato vencido" in _rota_lida(_rota(b))["motivos"]
    C.salvar_contrato({"id": b["ct"], "contratante_id": b["ctt"], "operador_id": b["op"], "inicio": _d(10)})
    assert _rota_lida(_rota(b, nome="R2"))["situacao"] == "bloqueado"
    with pytest.raises(ValueError):
        C.salvar_contrato({"contratante_id": b["ctt"], "operador_id": b["op"], "inicio": _d(10), "fim": _d(5)})


def test_avisos_lotacao_e_parada_sem_gps(banco):
    b = _base()
    paradas = _paradas() + [{"nome": "Sem GPS"}]
    rid = _rota(b, paradas=paradas)
    r = _rota_lida(rid)
    for i in range(4):
        C.salvar_aluno({"nome": f"Aluno {i}", "matricula": f"M{i}", "rota_id": rid, "parada_id": r["paradas"][0]["id"]})
    r = _rota_lida(rid)
    assert r["situacao"] == "atencao"
    assert "4 alunos para 3 lugares" in r["motivos"]
    assert any("sem localização" in m for m in r["motivos"])
    assert r["paradas"][0]["alunos"] == 4


def test_paradas_mantem_id_e_nao_somem_com_aluno(banco):
    b = _base()
    rid = _rota(b, paradas=_paradas(3))
    p = _rota_lida(rid)["paradas"]
    aid = C.salvar_aluno({"nome": "Aluno", "matricula": "M1", "rota_id": rid, "parada_id": p[1]["id"]})["id"]
    # reordena: a parada do aluno continua com o mesmo id
    nova = [dict(p[2], id=p[2]["id"]), dict(p[1], id=p[1]["id"]), dict(p[0], id=p[0]["id"])]
    C.salvar_rota({"id": rid, "nome": "Rota 07", "contrato_id": b["ct"], "paradas": nova})
    p2 = _rota_lida(rid)["paradas"]
    assert [x["id"] for x in p2] == [p[2]["id"], p[1]["id"], p[0]["id"]]
    assert next(a for a in C.cadastro()["alunos"] if a["id"] == aid)["parada_id"] == p[1]["id"]
    # tirar a parada que tem aluno: recusado e nada muda (transacao)
    with pytest.raises(ValueError, match="tem alunos"):
        C.salvar_rota({"id": rid, "nome": "Mudou", "contrato_id": b["ct"], "paradas": [p[0], p[2]]})
    r = _rota_lida(rid)
    assert r["nome"] == "Rota 07" and len(r["paradas"]) == 3
    # tirar uma sem aluno funciona
    C.salvar_rota({"id": rid, "nome": "Rota 07", "contrato_id": b["ct"], "paradas": [p[0], p[1]]})
    assert len(_rota_lida(rid)["paradas"]) == 2


def test_aluno_regras(banco):
    b = _base()
    r1 = _rota(b)
    r2 = _rota(b, nome="Outra")
    p_r2 = _rota_lida(r2)["paradas"][0]["id"]
    with pytest.raises(ValueError, match="outra rota"):
        C.salvar_aluno({"nome": "A", "rota_id": r1, "parada_id": p_r2})
    aid = C.salvar_aluno({"nome": "A", "rota_id": r1})["id"]
    a = next(x for x in C.cadastro()["alunos"] if x["id"] == aid)
    assert a["escola_id"] == b["esc"]  # herda a escola da rota
    assert a["situacao"] == "atencao" and "Sem parada" in a["motivos"]
    C.salvar_aluno({"nome": "B", "matricula": "2026-001"})
    with pytest.raises(ValueError, match="matrícula"):
        C.salvar_aluno({"nome": "C", "matricula": "2026-001"})


def test_motorista_e_monitor_na_funcao_certa(banco):
    b = _base()
    mon = R.salvar_motorista({"operador_id": b["op"], "nome": "Monitora", "funcao": "monitor"})["id"]
    with pytest.raises(ValueError, match="motorista"):
        _rota(b, motorista_id=mon)
    with pytest.raises(ValueError, match="monitor"):
        _rota(b, monitor_id=b["mot"])
    assert _rota_lida(_rota(b, monitor_id=mon))["situacao"] == "liberado"


def test_exclusao_bloqueada_em_uso(banco):
    b = _base()
    rid = _rota(b)
    C.salvar_aluno({"nome": "A", "rota_id": rid})
    for tabela, item in (("contratos", b["ct"]), ("veiculos", b["vei"]), ("motoristas", b["mot"]),
                         ("escolas", b["esc"]), ("rotas", rid), ("operadores", b["op"]), ("contratantes", b["ctt"])):
        with pytest.raises(ValueError, match="em uso"):
            R.excluir(tabela, item)


def test_rota_excluida_leva_as_paradas(banco):
    from app.services import db_store

    b = _base()
    rid = _rota(b)
    R.excluir("rotas", rid)
    with db_store._conn() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM rotas_paradas WHERE rota_id=?", (rid,)).fetchone()["n"] == 0


def test_isolamento_entre_clientes(banco):
    b = _base()
    rid = _rota(b)
    pid = _rota_lida(rid)["paradas"][0]["id"]
    tok = set_current_tenant_slug("empresa-y")
    try:
        assert C.cadastro()["rotas"] == [] and C.cadastro()["contratos"] == []
        with pytest.raises(ValueError):
            C.salvar_rota({"nome": "X", "contrato_id": b["ct"]})
        with pytest.raises(ValueError):
            C.salvar_aluno({"nome": "X", "rota_id": rid, "parada_id": pid})
        op = R.salvar_operador({"nome": "Y"})["id"]
        ctt = C.salvar_contratante({"nome": "Pref Y"})["id"]
        ct = C.salvar_contrato({"contratante_id": ctt, "operador_id": op})["id"]
        with pytest.raises(LookupError):  # editar a rota do outro cliente
            C.salvar_rota({"id": rid, "nome": "X", "contrato_id": ct})
        # contrato proprio, mas tentando sequestrar a parada do outro cliente
        with pytest.raises(ValueError, match="não pertence"):
            C.salvar_rota({"nome": "Y1", "contrato_id": ct, "paradas": [{"id": pid, "nome": "roubada"}]})
        for campo, alheio in (("veiculo_id", b["vei"]), ("motorista_id", b["mot"]), ("escola_id", b["esc"])):
            with pytest.raises(ValueError):
                C.salvar_rota({"nome": "Y2", "contrato_id": ct, campo: alheio})
        with pytest.raises(LookupError):
            R.excluir("rotas", rid)
    finally:
        reset_current_tenant_slug(tok)
    assert _rota_lida(rid)["paradas"][0]["nome"] == "Parada 1"


def test_validacoes(banco):
    b = _base()
    with pytest.raises(ValueError):
        C.salvar_escola({"nome": "E", "lat": "-10"})
    with pytest.raises(ValueError):
        _rota(b, paradas=[{"nome": "P", "horario": "25:00"}])
    with pytest.raises(ValueError):
        _rota(b, tolerancia_m="muito")
    with pytest.raises(ValueError):
        C.salvar_contrato({"contratante_id": b["ctt"], "operador_id": b["op"], "preco_km": "abc"})
    assert C._preco("R$ 12,5") == "12.5"
    assert C._preco("4.85") == "4.85"
