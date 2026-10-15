"""Importacao de pessoas por planilha: escola e condominio, atualizar sem
apagar nada, grupos acrescentados. SQLite temporario e pessoas ficticias."""
from __future__ import annotations

import pytest

from app.core import tenant_context
from app.services import access_control_import as I
from app.services import access_control_store as S
from app.services import db_store


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug("cliente-teste")
    S.ensure_access_control_schema()
    yield
    tenant_context.reset_current_tenant_slug(token)


def _csv(*linhas):
    return ("\n".join(";".join(l) for l in linhas)).encode("utf-8")


def test_condominio_sem_matricula_vira_morador_e_entra_no_grupo(banco, monkeypatch):
    monkeypatch.setattr(I, "_tipo_do_local", lambda site: "condominio")
    g = S.save_group({"name": "Moradores 24h", "site": "RESERVA"})
    planilha = _csv(["Nome", "CPF", "Unidade", "Tipo", "Grupo"],
                    ["ANA MORADORA", "529.982.247-25", "A01", "", "Moradores 24h"],
                    ["BETO PRESTADOR", "111.444.777-35", "", "prestador", "grupo que nao existe"])
    a = I.analisar_planilha(planilha, site="RESERVA")
    assert [r["person_type"] for r in a["criar"]] == ["resident", "contractor"]
    assert a["criar"][0]["class_name"] == "A01" and a["criar"][0]["grupos"] == [g["id"]]
    assert a["avisos"][0]["aviso"] == "grupo nao existe: grupo que nao existe"
    r = I.aplicar_planilha(planilha, site="RESERVA")
    assert r["criados"] == 2 and r["em_grupos"] == 1
    assert len(S.list_group_members(g["id"])) == 1


def test_aluno_sem_matricula_e_recusado(banco, monkeypatch):
    monkeypatch.setattr(I, "_tipo_do_local", lambda site: "escola")
    a = I.analisar_planilha(_csv(["Nome", "CPF"], ["ALUNO SEM MATRICULA", "52998224725"]), site="ESCOLA")
    assert a["recusados"][0]["motivo"] == "aluno precisa de matricula"


def test_reimportar_nao_apaga_telefone_id_no_leitor_local_nem_tipo(banco, monkeypatch):
    """O defeito antigo: save_person grava tudo; planilha sem coluna apagava."""
    monkeypatch.setattr(I, "_tipo_do_local", lambda site: "escola")
    p = S.save_person({"full_name": "PROFESSORA FICTICIA", "person_type": "employee", "document_id": "52998224725",
                       "site": "ESCOLA", "controller_user_id": "4242", "guardian_name": "", "guardian_phone": "82999990000",
                       "class_name": "Sala 3", "active": False, "notes": "nao mexer"})
    planilha = _csv(["Nome", "CPF"], ["PROFESSORA FICTICIA SOUZA", "529.982.247-25"])   # so nome e CPF
    a = I.analisar_planilha(planilha, site="")
    assert len(a["atualizar"]) == 1 and not a["criar"]
    I.aplicar_planilha(planilha, site="")
    depois = next(x for x in S.list_people() if x["id"] == p["id"])
    assert depois["full_name"] == "PROFESSORA FICTICIA SOUZA"            # o que veio, mudou
    assert depois["controller_user_id"] == "4242"                       # o resto ficou
    assert depois["guardian_phone"].endswith("82999990000")
    assert depois["site"] == "ESCOLA" and depois["class_name"] == "Sala 3"
    assert depois["person_type"] == "employee" and not depois["active"]
    assert depois["notes"] == "nao mexer"


def test_pessoa_nova_sem_local_e_recusada(banco, monkeypatch):
    monkeypatch.setattr(I, "_tipo_do_local", lambda site: "")
    a = I.analisar_planilha(_csv(["Nome", "CPF", "Tipo"], ["NOVA", "52998224725", "visitante"]), site="")
    assert "precisa de local" in a["recusados"][0]["motivo"]


def test_coluna_nome_do_responsavel_nao_vira_nome(banco):
    col = I._mapear_colunas(["Nome do responsável", "Nome", "CPF", "Celular do responsável", "Matrícula"])
    assert col["full_name"] == 1 and col["guardian_name"] == 0 and col["guardian_phone"] == 3
