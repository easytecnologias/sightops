"""A4: falha ao descobrir o site do conector no panico era engolida calada, e a
pessoa sem grupo de aviso nao aparecia na prontidao.

SQLite temporario, pessoas ficticias, nada de Telegram."""
from __future__ import annotations

import logging

import pytest

from app.api.endpoints import maintenance
from app.core import permissions, tenant_context
from app.services import alert_store as A
from app.services import db_store
from app.services import notificacoes_service as N

TENANT = "cliente-teste"


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug(TENANT)
    db_store.init_db()
    A._SITE_CONECTOR_CACHE.clear()
    from app.services import connector_service
    monkeypatch.setattr(connector_service, "get_connector", lambda cid, **kw: {"id": cid, "site": "ESCOLA"})
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: None)
    yield monkeypatch
    tenant_context.reset_current_tenant_slug(token)


def _membro():
    return {"member": {"full_name": "Pessoa", "unit_connector_id": "c1", "unit_name": "LOTACAO"}}


def test_falha_no_conector_loga_e_segue_pela_lotacao(banco, caplog):
    def cai(cid):
        raise RuntimeError("conector fora")

    banco.setattr(maintenance, "_site_do_conector", cai)
    with caplog.at_level(logging.WARNING, logger="cam-snapshot"):
        assert A._site_do_alerta(_membro()) == "LOTACAO"
    assert "conector fora" in caplog.text and "c1" in caplog.text


def test_conector_sem_site_tambem_avisa_no_log(banco, caplog):
    banco.setattr(maintenance, "_site_do_conector", lambda cid: "")
    with caplog.at_level(logging.WARNING, logger="cam-snapshot"):
        assert A._site_do_alerta(_membro()) == "LOTACAO"
    assert "sem site" in caplog.text


def _pendencias(nome):
    m = next(x for x in A.list_members() if x["full_name"] == nome)
    return m["prontidao"]


def test_prontidao_mostra_quem_esta_sem_grupo(banco):
    A.save_member({"full_name": "SEM GRUPO", "document_id": "52998224725", "unit_connector_id": "c1"})
    p = _pendencias("SEM GRUPO")
    assert "sem_grupo_aviso" in {x["codigo"] for x in p["pendencias"]}
    assert not next(x for x in p["pendencias"] if x["codigo"] == "sem_grupo_aviso")["bloqueia"]


def test_com_grupo_do_site_nao_tem_pendencia(banco):
    A.save_member({"full_name": "COM GRUPO", "document_id": "52998224725", "unit_connector_id": "c1"})
    N.salvar_grupo({"nome": "G", "chat_id": "-1001", "bot": "easy", "ativo": True, "sites": ["ESCOLA"], "eventos": ["panico"]})
    assert "sem_grupo_aviso" not in {x["codigo"] for x in _pendencias("COM GRUPO")["pendencias"]}


def test_nao_ler_os_grupos_nao_acusa_pendencia(banco):
    A.save_member({"full_name": "NAO SEI", "document_id": "52998224725", "unit_connector_id": "c1"})
    banco.setattr(N, "config", lambda: (_ for _ in ()).throw(RuntimeError("banco")))
    assert "sem_grupo_aviso" not in {x["codigo"] for x in _pendencias("NAO SEI")["pendencias"]}
