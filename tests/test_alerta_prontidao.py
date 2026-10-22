"""Alerta: prontidao das pessoas (consegue pedir ajuda agora?) e o aviso do app.

SQLite temporario, pessoas ficticias, nenhum celular de verdade."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core import permissions, tenant_context
from app.services import alert_store as A
from app.services import db_store

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


def _ativar(nome, cpf, pins=True):
    m = A.save_member({"full_name": nome, "document_id": cpf, "unit_connector_id": "c1"})
    code = A.create_activation_code(m["id"])["code"]
    out = A.activate_app(code, "teste", "web")
    ctx = A.resolve_app_session(out["token"])
    if pins:
        A.set_app_pins(ctx, "1234", "4321")
    return m, ctx, out["token"]


def _pessoa(nome):
    return next(m for m in A.list_members() if m["full_name"] == nome)


def _codigos(m):
    return {p["codigo"] for p in m["prontidao"]["pendencias"]}


def test_pessoa_pronta(banco):
    _, ctx, _ = _ativar("PRONTA", "52998224725")
    A.app_checkin(ctx, "granted", 80, "2")
    m = _pessoa("PRONTA")
    assert m["prontidao"]["pronta"] is True and _codigos(m) == set()
    assert m["device"]["gps_permission"] == "granted" and m["device"]["battery"] == 80


def test_pendencias_que_bloqueiam(banco):
    A.save_member({"full_name": "NUNCA ATIVOU", "document_id": "11144477735", "unit_connector_id": "c1"})
    _ativar("SEM SENHA", "39053344705", pins=False)
    _, ctx, _ = _ativar("GPS BLOQUEADO", "86288366757")
    A.app_checkin(ctx, "denied", 50)
    assert _codigos(_pessoa("NUNCA ATIVOU")) == {"sem_app"}
    assert _codigos(_pessoa("SEM SENHA")) == {"sem_senha"}
    assert _codigos(_pessoa("GPS BLOQUEADO")) == {"gps_bloqueado"}
    assert not any(_pessoa(n)["prontidao"]["pronta"] for n in ("NUNCA ATIVOU", "SEM SENHA", "GPS BLOQUEADO"))


def test_sem_sinal_ha_mais_de_7_dias(banco):
    _ativar("SUMIDA", "52998224725")
    m = _pessoa("SUMIDA")
    assert m["prontidao"]["pronta"]
    depois = A._now_dt() + timedelta(days=A.SINAL_MAX_DIAS + 2)
    p = A.prontidao_do_membro(m, agora=depois)
    assert not p["pronta"] and p["pendencias"][0]["codigo"] == "sem_sinal"


def test_bateria_e_sem_cameras_avisam_sem_bloquear(banco):
    _, ctx, _ = _ativar("BATERIA", "52998224725")
    A.app_checkin(ctx, "granted", 9)
    m = _pessoa("BATERIA")
    assert m["prontidao"]["pronta"] and _codigos(m) == {"bateria"}
    A.save_member({"id": m["id"], "full_name": "BATERIA", "document_id": "52998224725"})  # tira o local monitorado
    m = _pessoa("BATERIA")
    assert m["prontidao"]["pronta"] and _codigos(m) == {"bateria", "sem_cameras"}


def test_checkin_limpa_valor_estranho(banco):
    _, ctx, _ = _ativar("X", "52998224725")
    A.app_checkin(ctx, "'; drop table x", "abc", "v" * 100)
    d = _pessoa("X")["device"]
    assert d["gps_permission"] == "" and d["battery"] is None and len(d["app_version"]) <= 40


def test_checkin_pela_rota_do_app(banco):
    from fastapi.testclient import TestClient
    from app.main import app

    _, _, token = _ativar("ROTA", "52998224725")
    cli = TestClient(app)
    r = cli.post("/api/alert/app/checkin", json={"gps_permission": "granted", "battery": 77},
                 headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert _pessoa("ROTA")["device"]["battery"] == 77
    assert cli.post("/api/alert/app/checkin", json={}, headers={"Authorization": "Bearer errado"}).status_code == 401
