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


def test_rotas_ligadas_as_funcoes_certas():
    """O helper entre o decorador e a funcao roubou a rota /clip uma vez."""
    from app.api.endpoints import access_control, alert, playback

    rotas = {r.path: r.endpoint.__name__ for m in (playback, alert, access_control) for r in m.router.routes}
    assert rotas["/api/playback/clip"] == "create_clip"
    assert rotas["/api/alert/nearby-cameras"] == "api_alert_nearby_cameras"


def test_reproducao_confere_o_conector_do_download(restrito, monkeypatch):
    from app.api.endpoints import maintenance, playback

    vistos = []
    monkeypatch.setattr(maintenance, "alvo_permitido", lambda user, ip, nivel="ver", hint="": vistos.append(hint) or (True, ""))
    monkeypatch.setattr(playback, "_conector_do_gravador", lambda host, cid="": cid or "c-inventario")
    playback._conferir_gravador("10.0.0.1", "c-jang")
    playback._conferir_gravador("10.0.0.1")
    assert vistos == ["c-jang", "c-inventario"]


def test_controladora_por_id_de_outro_site(restrito, monkeypatch):
    from app.api.endpoints import access_control, maintenance

    monkeypatch.setattr(maintenance, "_site_do_conector", lambda cid: {"c-inco": "INCOFORTE", "c-jang": "JANGADEIROS"}.get(cid, ""))
    devs = [{"id": "d1", "site": "INCOFORTE", "connector_id": "c-inco"},
            {"id": "d2", "site": "JANGADEIROS", "connector_id": "c-jang"},
            {"id": "d3", "site": "", "connector_id": "c-inco"}]
    monkeypatch.setattr(access_control, "list_devices", lambda site="": [dict(d) for d in devs])
    access_control._exigir_controladora("d1")
    access_control._exigir_controladora("d3")
    with pytest.raises(HTTPException):
        access_control._exigir_controladora("d2")
    # "puxar" a controladora de outro site para o seu: barrado
    with pytest.raises(HTTPException):
        access_control._conferir_site_da_controladora({"id": "d2", "site": "INCOFORTE", "connector_id": "c-inco"})
    assert [d["id"] for d in access_control.api_access_control_devices()["devices"]] == ["d1", "d3"]


def test_onu_pelo_ip_da_olt_com_nome_repetido(tmp_path, monkeypatch):
    from app.api.endpoints import maintenance, tr069
    from app.services import db_store

    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(T, "DATA_DIR", tmp_path)
    db_store.init_db()
    monkeypatch.setattr(maintenance, "_site_do_conector", lambda cid: {"c-inco": "INCOFORTE", "c-jang": "JANGADEIROS"}.get(cid, ""))
    with db_store._conn() as c:
        c.execute("INSERT INTO olts(tenant_slug, name, host, connector_id) VALUES(?,?,?,?)", ("cliente-x", "OLT-FiberHome", "10.1.1.1", "c-inco"))
        c.execute("INSERT INTO olts(tenant_slug, name, host, connector_id) VALUES(?,?,?,?)", ("cliente-x", "OLT-FiberHome", "10.1.1.2", "c-jang"))
    tok = T.set_current_tenant_slug("cliente-x")
    try:
        onus = [{"serial": "A", "olt": "OLT-FiberHome", "olt_ip": "10.1.1.1"},
                {"serial": "B", "olt": "OLT-FiberHome", "olt_ip": "10.1.1.2"},
                {"serial": "C", "olt": "OLT-FiberHome", "olt_ip": "10.1.1.2", "site": "INCOFORTE"}]
        assert [o["serial"] for o in tr069._onus_dos_sites(onus, ["INCOFORTE"])] == ["A", "C"]
        assert [o["serial"] for o in tr069._onus_dos_sites(onus, ["JANGADEIROS"])] == ["B"]
    finally:
        T.reset_current_tenant_slug(tok)


def test_alerta_filtra_antes_do_corte(restrito, monkeypatch):
    from app.services import alert_store as A

    cams = [("olt", {"ip": f"10.0.0.{i}", "site": "JANGADEIROS" if i < 8 else "INCOFORTE", "d": i}) for i in range(10)]
    monkeypatch.setattr(A, "_inventory_cameras", lambda: cams)
    monkeypatch.setattr(A, "_camera_card", lambda mode, r, lat, lon: {"ip": r["ip"], "site": r["site"], "distance_m": r["d"]})
    from app.api.endpoints import alert

    r = alert.api_alert_nearby_cameras(lat=0, lon=0, limit=6, radius_m=100, accuracy_m=None)
    assert [c["ip"] for c in r["cameras"]] == ["10.0.0.8", "10.0.0.9"]


def test_painel_sem_dados_dos_modulos_ocultos(monkeypatch):
    from app.services import dashboard_service as D
    import app.services.monitoring_service as M

    u = _user("operator")
    monkeypatch.setattr(P, "modo", lambda: "valer")
    monkeypatch.setattr(P, "sites_do_usuario", lambda user, dados=None: [])
    monkeypatch.setattr(P, "niveis_do_usuario", lambda user, dados=None: {**{m: 2 for m in P._MODULO_KEYS}, "cameras": 0, "optica": 0})
    monkeypatch.setattr(D, "load_inventory_json", lambda mode="olt": [{"ip": "10.0.0.1", "status": "online"}])
    monkeypatch.setattr(D, "_recorder_rows", lambda tipo: [])
    monkeypatch.setattr(D, "load_windows_inventory", lambda: [])
    monkeypatch.setattr(M, "monitoring_summary", lambda sites=None: {"ok": True, "types": {"onu": {"total": 9}, "access_device": {"total": 2}},
                                                                     "events": [{"entity_type": "onu"}, {"entity_type": "access_device"}]})
    tok = T.set_current_user(u)
    try:
        r = D.build_dashboard_summary()
    finally:
        T.reset_current_user(tok)
    assert r["inventory"]["ip"]["total"] == 0
    assert list(r["monitoring"]["types"]) == ["access_device"]
    assert [e["entity_type"] for e in r["monitoring"]["events"]] == ["access_device"]
    assert set(r["modulos_ocultos"]) == {"cameras", "optica"}


def test_atividade_recente_sem_modulo_oculto():
    from app.services import dashboard_service as D

    itens = [{"label": "Inventario IP", "kind": "inventory"}, {"label": "Inventario NVR", "kind": "inventory"},
             {"label": "KMZ rede.kmz", "kind": "kmz"}, {"label": "Configuracoes", "kind": "settings"}]
    assert [i["label"] for i in D._atividade_visivel(itens, {"cameras", "mapa"})] == ["Inventario NVR", "Configuracoes"]
    assert D._atividade_visivel(itens, set()) == itens
