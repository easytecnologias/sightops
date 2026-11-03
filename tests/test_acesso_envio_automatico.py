"""Envio automatico (salvar pessoa/grupo/regra -> laco de reenvio) segue a regra
do "Enviar so o que falta": no Intelbras quem ja esta no leitor nao e tocado e
quem falta entra sem senha. SQLite temporario e leitor falso."""
from __future__ import annotations

import pytest

from app.core import tenant_context
from app.services import access_control_device as D
from app.services import access_control_store as S
from app.services import access_control_sync as Y
from app.services import db_store


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug("condominio-teste")
    S.ensure_access_control_schema()
    yield
    tenant_context.reset_current_tenant_slug(token)


@pytest.fixture()
def leitor_falso(monkeypatch):
    """Leitor com o usuario 3921 ja cadastrado; registra o que seria gravado."""
    cadastrados = {"3921"}
    gravados = []

    def ja_no_leitor(device, uid):
        return uid in cadastrados

    def cadastrar(device, person, foto=None, **kw):
        gravados.append({"uid": person["controller_user_id"], "foto": foto, **kw})
        return {"ok": True}

    def antigo(*a, **kw):
        raise AssertionError("caminho antigo (senha 123456) nao pode ser usado aqui")

    monkeypatch.setattr(Y, "_ja_no_leitor", ja_no_leitor)
    monkeypatch.setattr(D, "_provision_intelbras_person", cadastrar)
    monkeypatch.setattr(Y, "provision_person", antigo)
    return gravados


def _pendente(uid, ativa=True):
    leitor = S.save_device({"name": "ENTRADA", "site": "JARDINS", "vendor": "intelbras", "host": "10.0.0.9", "password": "x"})
    p = S.save_person({"full_name": "MORADOR FICTICIO", "person_type": "resident", "site": "JARDINS",
                       "controller_user_id": uid, "active": ativa})
    S.upsert_provision_status(p["id"], leitor["id"], "pending")
    return p, leitor


def test_quem_ja_esta_no_leitor_nao_e_tocado_e_fica_ok(banco, leitor_falso):
    p, _ = _pendente("3921")
    assert Y.retry_pending_provisions()["retried"] == 1
    assert leitor_falso == []
    assert [r["status"] for r in S.list_provision_status_for_person(p["id"])] == ["ok"]


def test_quem_falta_entra_sem_senha_e_com_validade_de_10_anos(banco, leitor_falso):
    p, _ = _pendente("5008")
    Y.retry_pending_provisions()
    assert len(leitor_falso) == 1
    g = leitor_falso[0]
    assert g["uid"] == "5008" and g["senha"] is None
    assert int(g["valido_ate"][:4]) - int(g["valido_de"][:4]) == 10
    assert [r["status"] for r in S.list_provision_status_for_person(p["id"])] == ["ok"]


def test_pessoa_desativada_segue_o_caminho_antigo(banco, monkeypatch):
    chamadas = []
    monkeypatch.setattr(Y, "_ja_no_leitor", lambda d, u: pytest.fail("nao consulta o leitor"))
    monkeypatch.setattr(Y, "provision_person", lambda d, p, f=None: chamadas.append(p["controller_user_id"]) or {"ok": True})
    _pendente("7001", ativa=False)
    Y.retry_pending_provisions()
    assert chamadas == ["7001"]


def test_passagem_liga_morador_de_outro_local_pelo_id_e_nome(monkeypatch):
    """Morador cadastrado na Reserva que passa no Jardins II: liga pelo ID no
    leitor (unico no cliente) se o nome bate; ID velho com outro nome, nao."""
    pessoas = [{"id": "p1", "full_name": "Dinho", "controller_user_id": "1300", "site": "RESERVA"},
               {"id": "p2", "full_name": "CÁSSIA CRISTINA", "controller_user_id": "5007", "site": "RESERVA"},
               {"id": "p3", "full_name": "Cleide", "controller_user_id": "5008", "site": "JARDINS II"}]
    monkeypatch.setattr(Y, "list_people", lambda site="": [p for p in pessoas if not site or p["site"] == site])
    assert Y._resolve_por_id_no_cliente({"user_id": "1300", "person_name_raw": "Dinho"})["id"] == "p1"
    assert Y._resolve_por_id_no_cliente({"user_id": "5007", "person_name_raw": "CÃ\x81SSIA CRISTINA DA SILVA"})["id"] == "p2"
    assert Y._resolve_por_id_no_cliente({"user_id": "5008", "person_name_raw": "GABRIEL GOMES"}) is None
    assert Y._resolve_por_id_no_cliente({"user_id": "", "person_name_raw": "Dinho"}) is None
    assert Y._resolve_por_id_no_cliente({"user_id": "9999", "person_name_raw": "X"}) is None
