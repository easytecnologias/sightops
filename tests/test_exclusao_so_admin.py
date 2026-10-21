"""Excluir, limpar e remover: so administrador e dono. O operador faz todo o
resto (reiniciar camera, gravacao, cadastrar pessoa na controladora). So dados
ficticios."""
from __future__ import annotations

from fastapi import FastAPI

from app.core import permissions as P
from app.core import security as SEC
from app.core.settings import get_settings


def _mw():
    return SEC.ApiAuthMiddleware(FastAPI(), get_settings())


def test_forma_da_rota():
    sim = [("DELETE", "/api/access-control/people/9"), ("POST", "/api/inventory/delete"),
           ("POST", "/api/olt/delete-onu"), ("POST", "/api/deployments/recorder-remove-camera"),
           ("POST", "/api/access-control/painel/pessoas/9/excluir"), ("POST", "/api/windows/clear"),
           ("POST", "/api/olt/clear")]
    nao = [("GET", "/api/inventory/delete"), ("POST", "/api/cameras/reboot"), ("POST", "/api/cameras/save"),
           ("POST", "/api/access-control/people"), ("POST", "/api/playback/clip"),
           ("DELETE", "/api/maintenance/web/10.0.0.1/cgi-bin/x"), ("POST", "/api/auth/logout"),
           ("POST", "/api/access-control/devices/d1/open-door")]
    assert [r for r in sim if not P.e_exclusao(r[1], r[0])] == []
    assert [r for r in nao if P.e_exclusao(r[1], r[0])] == []


def test_operador_nao_exclui_mas_opera():
    mw = _mw()
    for method, path in [("DELETE", "/api/access-control/people/9"), ("POST", "/api/inventory/clear"),
                         ("DELETE", "/api/connectors/c1"), ("DELETE", "/api/planning/projects/1"),
                         ("POST", "/api/olt/delete-onu")]:
        regra = mw._match_role_rule(path, method)
        assert regra == "admin", (method, path, regra)
        assert not mw._role_allows("operator", regra)
        assert mw._role_allows("admin", regra) and mw._role_allows("owner", regra)
    for method, path in [("POST", "/api/cameras/reboot"), ("POST", "/api/access-control/people"),
                         ("POST", "/api/playback/clip"), ("POST", "/api/connectors"),
                         ("DELETE", "/api/maintenance/web/10.0.0.1/x")]:
        assert mw._role_allows("operator", mw._match_role_rule(path, method)), (method, path)


def test_regra_nova_tambem_barra_operador():
    mw = _mw()
    op = {"id": 3, "role": "operator", "tenant_slug": "x", "effective_tenant_slug": "x", "effective_enabled_modules": None}
    ok, _ = P.decidir(op, "/api/access-control/people/9", "DELETE", mw._match_role_rule("/api/access-control/people/9", "DELETE"))
    assert not ok


def test_rota_sem_regra_continua_negada():
    assert _mw()._match_role_rule("/api/nao-existe/delete", "POST") == ""


import pytest
from fastapi import HTTPException

from app.core import tenant_context as T


def _como(role):
    return T.set_current_user({"id": 5, "username": "u5", "role": role, "tenant_slug": "x", "effective_tenant_slug": "x"})


def test_excecoes_de_uso_diario():
    assert not P.e_exclusao("/api/nvr/driver/casos/c1/itens/i2/remover", "POST")
    assert not P.e_exclusao("/api/alert/members/m1/revoke-devices", "POST")


def test_conector_so_admin_cria_instala_e_exclui():
    from fastapi.routing import APIRoute

    from app.api.endpoints import connectors as C

    admin = {(m, r.path) for r in C.router.routes if isinstance(r, APIRoute)
             for m in r.methods if any(d.call is C._so_admin for d in r.dependant.dependencies)}
    for alvo in [("POST", "/api/connectors"), ("DELETE", "/api/connectors/{connector_id}"),
                 ("GET", "/api/connectors/{connector_id}/agent-script"), ("GET", "/api/connectors/{connector_id}/routeros-script"),
                 ("POST", "/api/connectors/{connector_id}/wireguard"), ("POST", "/api/connectors/{connector_id}/ruijie/vpn"),
                 ("PUT", "/api/connectors/{connector_id}")]:
        assert alvo in admin, alvo
    for livre in [("GET", "/api/connectors"), ("POST", "/api/connectors/jobs"),
                  ("POST", "/api/connectors/{connector_id}/ruijie/lan-inventory")]:
        assert livre not in admin, livre
    tok = _como("operator")
    try:
        with pytest.raises(HTTPException):
            C._so_admin()
    finally:
        T.reset_current_user(tok)
    tok = _como("admin")
    try:
        C._so_admin()
    finally:
        T.reset_current_user(tok)


def test_operador_nao_exclui_por_dentro_de_rota_normal(monkeypatch):
    from app.api.endpoints import access_control as AC

    tok = _como("operator")
    try:
        assert not P.pode_excluir()
        monkeypatch.setattr(AC, "list_group_members", lambda gid: ["p1"])
        monkeypatch.setattr(AC, "save_group", lambda payload: (_ for _ in ()).throw(AssertionError("nao devia salvar")))
        with pytest.raises(HTTPException) as e:
            AC.api_access_control_save_group(AC.AccessGroupRequest(id="g1", name="G", member_ids=[]))
        assert e.value.status_code == 403
    finally:
        T.reset_current_user(tok)
    tok = _como("owner")
    try:
        assert P.pode_excluir()
    finally:
        T.reset_current_user(tok)
