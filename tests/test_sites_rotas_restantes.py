"""Fase 3b, rotas restantes: reproducao, painel, alerta, TR-069, controladoras,
token do conector e cache da web do equipamento. So dados ficticios."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import permissions as P
from app.core import tenant_context as T


def _user(role="viewer", uid=12, tenant="cliente-x"):
    return {"id": uid, "username": f"u{uid}", "role": role, "tenant_slug": tenant,
            "effective_tenant_slug": tenant, "effective_enabled_modules": None}


@pytest.fixture()
def restrito(monkeypatch):
    """Usuario restrito a INCOFORTE, com a regra valendo."""
    u = _user()
    monkeypatch.setattr(P, "modo", lambda: "valer")
    monkeypatch.setattr(P, "sites_do_usuario", lambda user, dados=None: ["INCOFORTE"] if user.get("role") != "owner" else [])
    tok = T.set_current_user(u)
    yield u
    T.reset_current_user(tok)


def test_reproducao_nega_gravador_de_outro_site(restrito, monkeypatch):
    from app.api.endpoints import maintenance, playback

    monkeypatch.setattr(maintenance, "alvo_permitido", lambda user, ip, nivel="ver", hint="": (ip == "10.0.0.1", "site fora"))
    playback._conferir_gravador("10.0.0.1")
    with pytest.raises(HTTPException) as e:
        playback._conferir_gravador("10.0.0.2")
    assert e.value.status_code == 403


def test_alerta_e_controladoras_filtrados(restrito):
    cams = [{"ip": "1", "site": "INCOFORTE"}, {"ip": "2", "site": "JANGADEIROS"}]
    assert [c["ip"] for c in P.filtrar_por_site(cams)] == ["1"]
    devs = [{"id": 1, "site": "incoforte"}, {"id": 2, "site": "JANGADEIROS", "local": "INCOFORTE"}]
    assert [d["id"] for d in P.filtrar_por_site(devs, ("site",))] == [1]


def test_controladora_nao_grava_fora_dos_sites(restrito, monkeypatch):
    from app.api.endpoints import access_control, maintenance

    monkeypatch.setattr(maintenance, "_site_do_conector", lambda cid: {"c-inco": "INCOFORTE", "c-jang": "JANGADEIROS"}.get(cid, ""))
    access_control._conferir_site_da_controladora({"site": "INCOFORTE", "connector_id": "c-inco"})
    for ruim in ({"site": "JANGADEIROS", "connector_id": "c-inco"}, {"site": "INCOFORTE", "connector_id": "c-jang"}):
        with pytest.raises(HTTPException):
            access_control._conferir_site_da_controladora(ruim)


def test_controladora_sem_regra_valendo_nao_confere(monkeypatch):
    from app.api.endpoints import access_control

    monkeypatch.setattr(P, "modo", lambda: "sombra")
    tok = T.set_current_user(_user())
    try:
        access_control._conferir_site_da_controladora({"site": "QUALQUER", "connector_id": "x"})
    finally:
        T.reset_current_user(tok)


def test_onus_pelo_site_da_olt(tmp_path, monkeypatch):
    from app.api.endpoints import maintenance, tr069
    from app.services import db_store

    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(T, "DATA_DIR", tmp_path)
    db_store.init_db()
    monkeypatch.setattr(maintenance, "_site_do_conector", lambda cid: "JANGADEIROS" if cid == "c-jang" else "")
    with db_store._conn() as c:
        c.execute("INSERT INTO sites(tenant_slug, name, active) VALUES(?,?,1)", ("cliente-x", "INCOFORTE"))
        sid = c.execute("SELECT id FROM sites WHERE name='INCOFORTE'").fetchone()["id"]
        c.execute("INSERT INTO olts(tenant_slug, name, host, site_id) VALUES(?,?,?,?)", ("cliente-x", "OLT INCO", "10.1.1.1", sid))
        c.execute("INSERT INTO olts(tenant_slug, name, host, connector_id) VALUES(?,?,?,?)", ("cliente-x", "OLT JANG", "10.1.1.2", "c-jang"))
    tok = T.set_current_tenant_slug("cliente-x")
    try:
        onus = [{"serial": "A", "olt": "OLT INCO"}, {"serial": "B", "olt": "OLT JANG"}, {"serial": "C", "olt": "SEM OLT"}]
        assert [o["serial"] for o in tr069._onus_dos_sites(onus, ["incoforte"])] == ["A"]
        assert [o["serial"] for o in tr069._onus_dos_sites(onus, ["JANGADEIROS"])] == ["B"]
    finally:
        T.reset_current_tenant_slug(tok)


def test_painel_inicial_usa_o_filtro(restrito, monkeypatch):
    from app.services import dashboard_service as D

    linhas = [{"ip": "10.0.0.1", "site": "INCOFORTE", "status": "online"}, {"ip": "10.0.0.2", "site": "JANGADEIROS", "status": "offline"}]
    monkeypatch.setattr(D, "load_inventory_json", lambda mode="olt": list(linhas))
    monkeypatch.setattr(D, "_recorder_rows", lambda tipo: [])
    monkeypatch.setattr(D, "load_windows_inventory", lambda: [])
    vistos = {}
    import app.services.monitoring_service as M

    monkeypatch.setattr(M, "monitoring_summary", lambda sites=None: vistos.setdefault("sites", sites) and {"ok": True, "types": {}, "events": []})
    r = D.build_dashboard_summary()
    assert r["inventory"]["ip"]["total"] == 1
    assert vistos["sites"] == ["INCOFORTE"]


def test_token_do_conector_so_para_admin(monkeypatch):
    from app.api.endpoints import connectors

    pedidos = []
    monkeypatch.setattr(connectors, "get_connector", lambda cid, include_token=False, enforce_tenant=False: pedidos.append(include_token) or {"id": cid})
    for papel, esperado in (("operator", False), ("viewer", False), ("admin", True), ("owner", True)):
        tok = T.set_current_user(_user(papel))
        try:
            connectors.api_connectors_get("c1")
        finally:
            T.reset_current_user(tok)
        assert pedidos[-1] is esperado


def test_web_do_equipamento_nao_fica_na_borda():
    import inspect

    from app.api.endpoints import maintenance

    fonte = inspect.getsource(maintenance)
    assert 'f"public, max-age={_CDN_CACHE_MAX_AGE_SECONDS}"' not in fonte
    assert fonte.count('f"private, max-age={_CDN_CACHE_MAX_AGE_SECONDS}"') == 2
