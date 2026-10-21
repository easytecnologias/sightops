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
           ("POST", "/api/nvr/driver/casos/1/itens/2/remover"), ("POST", "/api/alert/members/3/revoke-devices")]
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
