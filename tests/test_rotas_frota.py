"""Controle de Rotas: cadastro da frota com banco SQLite de verdade (tmp).
So dados ficticios."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core import permissions as P
from app.core import security as SEC
from app.core.settings import get_settings
from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import rotas_store as R

HOJE = date(2026, 10, 23)


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


def _operador(nome="Empresa A"):
    return R.salvar_operador({"nome": nome, "tipo": "empresa", "documento": "12.345.678/0001-90"})["id"]


def test_situacao_do_documento():
    assert R.situacao_doc("", HOJE)["st"] == "faltando"
    assert R.situacao_doc(_d(-1), HOJE)["st"] == "vencido"
    assert R.situacao_doc(_d(0), HOJE)["st"] == "vence"
    assert R.situacao_doc(_d(30), HOJE)["st"] == "vence"
    assert R.situacao_doc(_d(31), HOJE)["st"] == "ok"


def test_veiculo_vistoria_vencida_bloqueia_seguro_so_avisa():
    base = {"ativo": 1, "vistoria_validade": _d(200), "autorizacao_validade": _d(200), "seguro_validade": _d(200)}
    assert R.situacao_veiculo(base, HOJE)["situacao"] == "liberado"
    assert R.situacao_veiculo({**base, "seguro_validade": _d(-3)}, HOJE)["situacao"] == "atencao"
    assert R.situacao_veiculo({**base, "vistoria_validade": _d(-3)}, HOJE)["situacao"] == "bloqueado"
    assert R.situacao_veiculo({**base, "autorizacao_validade": ""}, HOJE)["situacao"] == "bloqueado"
    assert R.situacao_veiculo({**base, "vistoria_validade": _d(5)}, HOJE)["situacao"] == "atencao"
    assert R.situacao_veiculo({**base, "ativo": 0, "vistoria_validade": ""}, HOJE)["situacao"] == "inativo"


def test_motorista_precisa_de_d_ou_e_e_curso_monitor_nao():
    base = {"ativo": 1, "funcao": "motorista", "cnh_categoria": "D", "cnh_validade": _d(400), "curso_validade": _d(400)}
    assert R.situacao_motorista(base, HOJE)["situacao"] == "liberado"
    assert R.situacao_motorista({**base, "cnh_categoria": "B"}, HOJE)["situacao"] == "bloqueado"
    assert R.situacao_motorista({**base, "curso_validade": ""}, HOJE)["situacao"] == "bloqueado"
    assert R.situacao_motorista({**base, "cnh_validade": _d(-1)}, HOJE)["situacao"] == "bloqueado"
    assert R.situacao_motorista({"ativo": 1, "funcao": "monitor"}, HOJE)["situacao"] == "liberado"


def test_cadastro_real_e_resumo(banco):
    op = _operador()
    R.salvar_veiculo({"operador_id": op, "placa": "qrt-4b21", "lugares": "29",
                      "vistoria_validade": _d(200), "autorizacao_validade": _d(200), "seguro_validade": _d(200)})
    R.salvar_veiculo({"operador_id": op, "placa": "RZD5F88", "vistoria_validade": _d(-8), "autorizacao_validade": _d(60)})
    R.salvar_motorista({"operador_id": op, "nome": "Motorista Teste", "cpf": "111.444.777-35",
                        "cnh_categoria": "AD", "cnh_validade": _d(500), "curso_validade": _d(500)})
    f = R.frota(HOJE)
    placas = {v["placa"]: v["situacao"] for v in f["veiculos"]}
    assert placas == {"QRT4B21": "liberado", "RZD5F88": "bloqueado"}
    assert f["motoristas"][0]["cnh_categoria"] == "D"
    assert f["motoristas"][0]["situacao"] == "liberado"
    assert f["resumo"]["veiculos_liberados"] == 1 and f["resumo"]["bloqueados"] == 1
    assert f["operadores"][0]["veiculos"] == 2


def test_placa_e_cpf_repetidos_sao_recusados(banco):
    op = _operador()
    R.salvar_veiculo({"operador_id": op, "placa": "ABC1234"})
    with pytest.raises(ValueError, match="placa"):
        R.salvar_veiculo({"operador_id": op, "placa": "abc-1234"})
    R.salvar_motorista({"operador_id": op, "nome": "Um", "cpf": "11144477735"})
    with pytest.raises(ValueError, match="CPF"):
        R.salvar_motorista({"operador_id": op, "nome": "Dois", "cpf": "111.444.777-35"})


def test_validacoes(banco):
    op = _operador()
    with pytest.raises(ValueError):
        R.salvar_veiculo({"operador_id": op, "placa": "123"})
    with pytest.raises(ValueError):
        R.salvar_veiculo({"operador_id": "nao-existe", "placa": "ABC1234"})
    with pytest.raises(ValueError):
        R.salvar_veiculo({"operador_id": op, "placa": "ABC1234", "vistoria_validade": "31/12/2026"})
    with pytest.raises(ValueError):
        R.salvar_motorista({"operador_id": op, "nome": "X", "funcao": "piloto"})
    # "nao" e string verdadeira em Python: tem que desativar mesmo assim.
    vid = R.salvar_veiculo({"operador_id": op, "placa": "ABC1234", "ativo": "nao"})["id"]
    assert next(v for v in R.frota(HOJE)["veiculos"] if v["id"] == vid)["ativo"] == 0


def test_cliente_nao_ve_nem_altera_frota_do_outro(banco):
    op = _operador()
    vid = R.salvar_veiculo({"operador_id": op, "placa": "ABC1234"})["id"]
    tok = set_current_tenant_slug("empresa-y")
    try:
        f = R.frota(HOJE)
        assert f["veiculos"] == [] and f["operadores"] == []
        with pytest.raises(ValueError):  # operador do outro cliente nao existe aqui
            R.salvar_veiculo({"operador_id": op, "placa": "XYZ9876"})
        with pytest.raises(LookupError):
            R.salvar_veiculo({"id": vid, "operador_id": _operador("Minha"), "placa": "ABC1234"})
        with pytest.raises(LookupError):
            R.excluir("veiculos", vid)
        # a mesma placa pode existir em outro cliente
        R.salvar_veiculo({"operador_id": _operador("Outra"), "placa": "ABC1234"})
    finally:
        reset_current_tenant_slug(tok)
    assert [v["id"] for v in R.frota(HOJE)["veiculos"]] == [vid]


def test_operador_com_frota_nao_pode_ser_excluido(banco):
    op = _operador()
    vid = R.salvar_veiculo({"operador_id": op, "placa": "ABC1234"})["id"]
    with pytest.raises(ValueError):
        R.excluir("operadores", op)
    R.excluir("veiculos", vid)
    R.excluir("operadores", op)
    assert R.frota(HOJE)["operadores"] == []
    with pytest.raises(LookupError):
        R.excluir("usuarios", "1")


def test_rotas_no_modulo_e_exclusao_so_admin():
    from fastapi import FastAPI

    assert P.modulo_da_rota("/api/rotas/frota") == "rotas"
    sec = SEC.ApiAuthMiddleware(FastAPI(), get_settings())
    assert sec._match_role_rule("/api/rotas/veiculos", "POST") == "operator"
    assert sec._match_role_rule("/api/rotas/veiculos/abc", "DELETE") == "admin"
