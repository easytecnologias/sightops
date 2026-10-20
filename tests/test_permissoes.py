"""Fase 3: permissao por modulo x nivel. O ponto central e a equivalencia: sem
perfil personalizado e sem modulo restrito, a regra nova decide EXATAMENTE como a
antiga em todas as rotas da aplicacao. So dados ficticios."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import permissions as P
from app.core import security as SEC
from app.core.settings import get_settings

ROLES = ("viewer", "operator", "admin", "owner")


def _user(role, uid=7, modulos=None, tenant="cliente-x"):
    return {"id": uid, "username": f"u{uid}", "role": role, "tenant_slug": tenant,
            "effective_tenant_slug": tenant, "effective_enabled_modules": modulos}


@pytest.fixture()
def sem_banco(monkeypatch):
    """Perfis em memoria, sem json_state."""
    store = {}
    monkeypatch.setattr(P, "carregar_perfis", lambda slug, usar_cache=True: store.setdefault(slug, {"profiles": {}, "users": {}}))
    monkeypatch.setattr(P, "salvar_perfis", lambda slug, dados: store.__setitem__(slug, dados))
    monkeypatch.setattr(P, "modo", lambda: "sombra")
    P._limpar_cache_para_testes()
    return store


def _rotas():
    from app.main import app

    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method in ops:
            m = method.upper()
            if m not in ("HEAD", "OPTIONS"):
                yield m, path.replace("{", "x").replace("}", "")


def test_regra_nova_igual_a_antiga_em_todas_as_rotas(sem_banco):
    mw = SEC.ApiAuthMiddleware(FastAPI(), get_settings())
    rotas = list(_rotas())
    assert len(rotas) > 400
    diferentes = []
    for method, path in rotas:
        if mw._is_public_path(path):
            continue
        regra = mw._match_role_rule(path, method)
        for role in ROLES:
            if not regra and method in mw._WRITE_METHODS:
                antiga = False
            else:
                antiga = not regra or mw._role_allows(role, regra)
            nova, _ = P.decidir(_user(role), path, method, regra)
            if nova != antiga:
                diferentes.append((role, method, path, antiga, nova))
    assert not diferentes, diferentes[:20]


def test_toda_rota_tem_modulo_ou_e_do_nucleo():
    nucleo = ("/api/auth/", "/api/dashboard/", "/api/system/")
    soltas = sorted({p for _, p in _rotas() if not P.modulo_da_rota(p) and not p.startswith(nucleo)})
    assert not soltas, soltas


def test_modulo_fora_do_plano_e_negado_no_backend(sem_banco):
    u = _user("admin", modulos=["inv-olt", "inv-nvr"])
    assert P.decidir(u, "/api/cameras/save", "POST", "operator")[0]
    ok, motivo = P.decidir(u, "/api/access-control/doors/open", "POST", "operator")
    assert not ok and "fora do plano" in motivo
    assert P.decidir(u, "/api/auth/users", "GET", "admin")[0]  # Administracao nao sai do plano


def test_perfil_personalizado_e_ajuste_por_usuario(sem_banco):
    P.salvar_perfil("cliente-x", "portaria", "Portaria", {"acesso": "operar", "cameras": "ver", "gravadores": 0})
    portaria = _user("viewer", uid=12)
    P.definir_acesso_usuario("cliente-x", portaria, "portaria", {"alerta": "operar"})
    n = P.niveis_do_usuario(portaria)
    assert (n["acesso"], n["cameras"], n["gravadores"], n["alerta"], n["optica"]) == (2, 1, 0, 2, 1)
    assert P.decidir(portaria, "/api/access-control/doors/open", "POST", "operator")[0]
    assert not P.decidir(portaria, "/api/nvr/inventory", "GET", "")[0]  # gravadores sem acesso


def test_administracao_nao_passa_do_perfil_fixo(sem_banco):
    P.salvar_perfil("cliente-x", "chefe", "Chefe", {"administracao": "administrar"})
    op = _user("operator", uid=13)
    P.definir_acesso_usuario("cliente-x", op, "chefe", {})
    assert P.niveis_do_usuario(op)["administracao"] == 2
    assert not P.decidir(op, "/api/auth/users", "POST", "admin")[0]


def test_dono_nao_pode_ser_restringido(sem_banco):
    with pytest.raises(ValueError):
        P.definir_acesso_usuario("cliente-x", _user("owner", uid=1), "", {"cameras": 0})
    assert set(P.niveis_do_usuario(_user("owner")).values()) == {3}


def test_validacoes(sem_banco):
    for args in [("cliente-x", "viewer", "X", {}), ("cliente-x", "p", "", {}), ("cliente-x", "p", "P", {"nao-existe": 1}),
                 ("cliente-x", "p", "P", {"cameras": 9})]:
        with pytest.raises(ValueError):
            P.salvar_perfil(*args)
    P.salvar_perfil("cliente-x", "p", "P", {})
    P.definir_acesso_usuario("cliente-x", _user("viewer", uid=5), "p", {})
    with pytest.raises(ValueError):
        P.excluir_perfil("cliente-x", "p")  # em uso


def test_perfis_de_um_cliente_nao_valem_no_outro(sem_banco):
    P.salvar_perfil("cliente-x", "portaria", "Portaria", {"acesso": "operar"})
    P.definir_acesso_usuario("cliente-x", _user("viewer", uid=12), "portaria", {})
    outro = _user("viewer", uid=12, tenant="cliente-y")  # mesmo id, outro cliente
    assert P.niveis_do_usuario(outro)["acesso"] == 1


# --------------------------------------------------------------------------- middleware

def _app(monkeypatch, usuario):
    app = FastAPI()

    @app.post("/api/access-control/doors/open")
    def abrir():
        return {"ok": True}

    @app.get("/api/cameras/list")
    def listar():
        return {"ok": True}

    import dataclasses

    settings = dataclasses.replace(get_settings(), auth_enabled=True, auth_required=True)
    app.add_middleware(SEC.ApiAuthMiddleware, settings=settings)
    monkeypatch.setattr(SEC, "get_user_by_token", lambda tok: usuario)
    return TestClient(app)


def test_sombra_vale_a_antiga_e_registra_a_divergencia(sem_banco, monkeypatch):
    P.salvar_perfil("cliente-x", "portaria", "Portaria", {"acesso": "operar"})
    viewer = _user("viewer", uid=12)
    P.definir_acesso_usuario("cliente-x", viewer, "portaria", {})
    c = _app(monkeypatch, viewer)
    r = c.post("/api/access-control/doors/open", headers={"Authorization": "Bearer t"})
    assert r.status_code == 403  # antiga: viewer nao abre porta
    g = P.resumo_sombra()["grupos"]
    assert g and g[0]["mudanca"] == "negava->permite" and g[0]["tenant"] == "cliente-x"


def test_valer_usa_a_nova(sem_banco, monkeypatch):
    P.salvar_perfil("cliente-x", "portaria", "Portaria", {"acesso": "operar", "cameras": 0})
    viewer = _user("viewer", uid=12)
    P.definir_acesso_usuario("cliente-x", viewer, "portaria", {})
    monkeypatch.setattr(P, "modo", lambda: "valer")
    c = _app(monkeypatch, viewer)
    assert c.post("/api/access-control/doors/open", headers={"Authorization": "Bearer t"}).status_code == 200
    r = c.get("/api/cameras/list", headers={"Authorization": "Bearer t"})
    assert r.status_code == 403 and "cameras" in r.json()["detail"]


def test_regra_nova_quebrada_nao_derruba_requisicao(sem_banco, monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(P, "decidir", quebra)
    monkeypatch.setattr(P, "modo", lambda: "valer")
    c = _app(monkeypatch, _user("operator"))
    assert c.post("/api/access-control/doors/open", headers={"Authorization": "Bearer t"}).status_code == 200
    assert c.get("/api/cameras/list", headers={"Authorization": "Bearer t"}).status_code == 200


def test_gravacao_e_leitura_reais_no_banco(tmp_path, monkeypatch):
    from app.core import tenant_context
    from app.services import db_store

    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    db_store.init_db()
    P._limpar_cache_para_testes()
    P.salvar_perfil("cliente-x", "portaria", "Portaria", {"acesso": "operar"})
    P.definir_acesso_usuario("cliente-x", _user("viewer", uid=12), "portaria", {})
    P._limpar_cache_para_testes()
    assert P.niveis_do_usuario(_user("viewer", uid=12))["acesso"] == 2
    assert P.carregar_perfis("cliente-y")["profiles"] == {}
    assert P.modo() == "sombra"
    P.definir_modo({"is_platform_admin": 1, "username": "dono"}, "valer")
    P._limpar_cache_para_testes()
    assert P.modo() == "valer"
    with pytest.raises(PermissionError):
        P.definir_modo({"is_platform_admin": 0}, "sombra")


def test_menu_esconde_tela_sem_acesso_so_quando_vale(sem_banco, monkeypatch):
    P.salvar_perfil("cliente-x", "portaria", "Portaria", {"gravadores": 0, "implantacao": 0, "cameras": 1})
    u = _user("viewer", uid=12)
    P.definir_acesso_usuario("cliente-x", u, "portaria", {})
    assert P.views_sem_acesso(u) == []  # sombra: menu como antes
    monkeypatch.setattr(P, "modo", lambda: "valer")
    v = P.views_sem_acesso(u)
    assert "inv-nvr" in v and "mnt-nvr" in v
    assert "deploy-new" not in v  # tambem e de Cameras, que ele ve
    assert "inv-olt" not in v
