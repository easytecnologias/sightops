"""Alerta: etapa "equipe chegou ao local" e passos do atendimento por site.

SQLite temporario, pessoas e sites ficticios."""
from __future__ import annotations

import pytest

from app.core import permissions, tenant_context
from app.services import alert_store as A
from app.services import db_store

TENANT = "cliente-teste"
CONECTORES = {"c-medea": "ESCOLA MEDEA", "c-porto": "PORTO REAL"}


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
    monkeypatch.setattr(connector_service, "get_connector",
                        lambda cid, **kw: {"id": cid, "site": CONECTORES.get(cid, "")})
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: None)
    monkeypatch.setattr(permissions, "sites_do_cliente",
                        lambda t: [{"name": "ESCOLA MEDEA", "equipamentos": 1}, {"name": "PORTO REAL", "equipamentos": 1}])
    yield monkeypatch
    tenant_context.reset_current_tenant_slug(token)


def _alerta(nome, cpf, conector):
    m = A.save_member({"full_name": nome, "document_id": cpf, "unit_connector_id": conector})
    ctx = {"tenant_slug": TENANT, "member": {"id": m["id"], "full_name": nome}}
    return A.trigger_incident(ctx, {})["incident"]["id"]


def test_chegada_depois_de_assumir(banco):
    inc = _alerta("A", "52998224725", "c-medea")
    with pytest.raises(ValueError):          # ninguem assumiu ainda
        A.transition_incident(inc, "arrive", "op")
    A.transition_incident(inc, "acknowledge", "op")
    out = A.transition_incident(inc, "arrive", "op")
    assert out["arrived_at"] and out["arrived_by"] == "op"
    assert out["status"] == "dispatched" and out["dispatched_at"]   # chegou = equipe foi
    assert out["log"][-1]["action"] == "arrive"
    with pytest.raises(ValueError):          # nao marca duas vezes
        A.transition_incident(inc, "arrive", "op")
    assert A.transition_incident(inc, "close", "op", "resolvido")["status"] == "closed"


def test_passos_do_site_e_padrao(banco):
    A.salvar_protocolo("*", ["Ver cameras"])
    A.salvar_protocolo("escola medea", ["Acionar viatura", "Avisar direcao", "Acionar viatura", " "])
    medea = _alerta("A", "52998224725", "c-medea")
    porto = _alerta("B", "11144477735", "c-porto")
    assert [p["texto"] for p in A.get_incident(medea)["protocolo"]] == ["Acionar viatura", "Avisar direcao"]
    assert [p["texto"] for p in A.get_incident(porto)["protocolo"]] == ["Ver cameras"]   # sem lista: padrao

    out = A.marcar_passo(medea, "op", "Avisar direcao")
    feito = {p["texto"]: p for p in out["protocolo"]}
    assert feito["Avisar direcao"]["feito"] and feito["Avisar direcao"]["por"] == "op"
    assert not feito["Acionar viatura"]["feito"]
    out = A.marcar_passo(medea, "op", "Avisar direcao", feito=False)
    assert not any(p["feito"] for p in out["protocolo"])
    with pytest.raises(ValueError):
        A.marcar_passo(medea, "op", "passo inventado")


def test_restrito_so_edita_os_sites_dele(banco):
    banco.setattr(permissions, "sites_da_sessao", lambda: ["ESCOLA MEDEA"])
    lista = A.listar_protocolos()
    assert [s["site"] for s in lista["sites"]] == ["ESCOLA MEDEA"] and lista["pode_padrao"] is False
    assert "padrao" not in lista
    A.salvar_protocolo("ESCOLA MEDEA", ["Acionar viatura"])
    for site in ("PORTO REAL", "*", "SITE INVENTADO"):
        with pytest.raises(ValueError):
            A.salvar_protocolo(site, ["x"])


def test_limites_da_lista(banco):
    with pytest.raises(ValueError):
        A.salvar_protocolo("PORTO REAL", [f"passo {i}" for i in range(20)])
    A.salvar_protocolo("PORTO REAL", ["a"])
    A.salvar_protocolo("PORTO REAL", [])          # lista vazia apaga
    assert all(not s["passos"] for s in A.listar_protocolos()["sites"])


def test_salvar_passos_exige_admin():
    from app.core.security import ApiAuthMiddleware
    from app.core.settings import get_settings

    async def app_vazio(scope, receive, send):
        return None

    regras = ApiAuthMiddleware(app_vazio, get_settings())
    assert regras._match_role_rule("/api/alert/protocols", "PUT") == "admin"
    assert regras._match_role_rule("/api/alert/incidents/x/arrive", "POST") == "operator"
    assert regras._match_role_rule("/api/alert/incidents/x/step", "POST") == "operator"
