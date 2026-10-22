"""Alerta: usuario restrito a sites so ve, ouve e atende alerta dos sites dele.

SQLite temporario, pessoas e conectores ficticios. O site da pessoa e o do
conector da lotacao; sem conector, o nome da lotacao."""
from __future__ import annotations

import pytest

from app.core import permissions, tenant_context
from app.services import alert_store as A
from app.services import db_store

CONECTORES = {"c-medea": "ESCOLA MEDEA", "c-porto": "PORTO REAL"}


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug("cliente-teste")
    db_store.init_db()
    A._SITE_CONECTOR_CACHE.clear()
    from app.services import connector_service
    monkeypatch.setattr(connector_service, "get_connector",
                        lambda cid, **kw: {"id": cid, "site": CONECTORES.get(cid, "")})
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: None)
    yield monkeypatch
    tenant_context.reset_current_tenant_slug(token)


def _pessoa(nome, cpf, conector="", lotacao=""):
    return A.save_member({"full_name": nome, "document_id": cpf, "unit_connector_id": conector, "unit_name": lotacao})


def _cenario():
    medea = _pessoa("PESSOA MEDEA", "52998224725", conector="c-medea")
    porto = _pessoa("PESSOA PORTO", "11144477735", conector="c-porto")
    solta = _pessoa("PESSOA SEM CONECTOR", "39053344705", lotacao="Escola Medea")  # site pelo nome da lotacao
    ctx = lambda m: {"tenant_slug": "cliente-teste", "member": {"id": m["id"], "full_name": m["full_name"]}}
    inc_medea = A.trigger_incident(ctx(medea), {})["incident"]["id"]
    inc_porto = A.trigger_incident(ctx(porto), {})["incident"]["id"]
    return {"medea": medea, "porto": porto, "solta": solta, "inc_medea": inc_medea, "inc_porto": inc_porto}


def _restringir(mp, *sites):
    mp.setattr(permissions, "sites_da_sessao", lambda: list(sites))


def test_sem_restricao_ve_tudo(banco):
    c = _cenario()
    assert len(A.list_members()) == 3
    assert {i["id"] for i in A.list_incidents()} == {c["inc_medea"], c["inc_porto"]}
    assert A.live_summary()["new"] == 2
    assert {i["site"] for i in A.list_incidents()} == {"ESCOLA MEDEA", "PORTO REAL"}


def test_restrito_so_ve_pessoas_e_alertas_do_site(banco):
    c = _cenario()
    _restringir(banco, "Escola Medea")
    assert sorted(m["full_name"] for m in A.list_members()) == ["PESSOA MEDEA", "PESSOA SEM CONECTOR"]
    assert [i["id"] for i in A.list_incidents()] == [c["inc_medea"]]
    assert [i["id"] for i in A.list_incidents(scope="history")] == [c["inc_medea"]]
    s = A.live_summary()
    assert (s["open"], s["new"], s["latest_new_id"]) == (1, 1, c["inc_medea"])


def test_restrito_nao_abre_nem_atende_alerta_de_outro_site(banco):
    c = _cenario()
    _restringir(banco, "ESCOLA MEDEA")
    with pytest.raises(LookupError):
        A.get_incident(c["inc_porto"])
    with pytest.raises(LookupError):
        A.transition_incident(c["inc_porto"], "acknowledge", "op")
    with pytest.raises(LookupError):
        A.add_incident_note(c["inc_porto"], "op", "x")
    assert A.transition_incident(c["inc_medea"], "acknowledge", "op")["status"] == "acknowledged"
    banco.setattr(permissions, "sites_da_sessao", lambda: None)
    assert A.get_incident(c["inc_porto"])["status"] == "new"   # nada mudou no alerta alheio


def test_restrito_nao_mexe_em_pessoa_de_outro_site(banco):
    c = _cenario()
    _restringir(banco, "ESCOLA MEDEA")
    pid = c["porto"]["id"]
    for acao in (A.create_activation_code, A.revoke_member_devices, A.delete_member):
        with pytest.raises(ValueError):
            acao(pid)
    with pytest.raises(ValueError):
        A.save_member({"id": pid, "full_name": "X", "document_id": "11144477735", "unit_connector_id": "c-medea"})
    with pytest.raises(ValueError):   # pessoa nova em site que ele nao ve
        _pessoa("NOVA", "86288366757", conector="c-porto")
    assert _pessoa("NOVA", "86288366757", conector="c-medea")["site"] == "ESCOLA MEDEA"
    assert A.create_activation_code(c["medea"]["id"])["code"]


def test_sem_site_some_para_restrito(banco):
    _pessoa("SEM LOTACAO", "52998224725")
    _restringir(banco, "ESCOLA MEDEA")
    assert A.list_members() == []


def test_cpf_repetido_nao_revela_pessoa_de_outro_site(banco):
    _cenario()
    _restringir(banco, "ESCOLA MEDEA")
    with pytest.raises(ValueError) as e:   # CPF da PESSOA PORTO
        _pessoa("OUTRA", "11144477735", conector="c-medea")
    assert "PORTO" not in str(e.value)
    with pytest.raises(ValueError) as e:   # CPF de alguem do proprio site: pode dizer quem
        _pessoa("OUTRA", "52998224725", conector="c-medea")
    assert "PESSOA MEDEA" in str(e.value)


def test_conector_com_erro_nao_cai_no_nome_da_lotacao(banco):
    from app.services import connector_service
    _pessoa("PORTO COM NOME ERRADO", "52998224725", conector="c-porto", lotacao="ESCOLA MEDEA")
    def quebra(*a, **k):
        raise RuntimeError("conectores.json ilegivel")
    banco.setattr(connector_service, "get_connector", quebra)
    A._SITE_CONECTOR_CACHE.clear()
    _restringir(banco, "ESCOLA MEDEA")
    assert A.list_members() == []
