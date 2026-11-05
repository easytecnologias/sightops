"""Proxy web do equipamento (/api/maintenance/web/): operador em qualquer
metodo, nos dois modos de permissao. GET na camera tambem reinicia/abre porta.
So dados ficticios; nenhum equipamento e chamado."""
from __future__ import annotations

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import permissions as P
from app.core import security as SEC
from app.core.settings import get_settings

H = {"Authorization": "Bearer x"}
VIEWER = {"id": 7, "username": "portaria", "role": "viewer", "tenant_slug": "cli",
          "effective_tenant_slug": "cli", "effective_enabled_modules": None}
OPERADOR = {**VIEWER, "id": 8, "username": "op", "role": "operator"}
METODOS = ["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]
ROTA = "/api/maintenance/web/10.0.0.9/cgi-bin/magicBox.cgi"


def test_regra_operator_em_todo_metodo():
    mw = SEC.ApiAuthMiddleware(FastAPI(), get_settings())
    for m in METODOS:
        assert mw._match_role_rule(ROTA, m) == "operator", m


def _cliente(monkeypatch, usuario, modo):
    app = FastAPI()
    app.add_api_route("/api/maintenance/web/{ip}/{path:path}", lambda ip, path: {"ok": True}, methods=METODOS)
    settings = dataclasses.replace(get_settings(), auth_enabled=True, auth_required=True)
    app.add_middleware(SEC.ApiAuthMiddleware, settings=settings)
    monkeypatch.setattr(SEC, "get_user_by_token", lambda tok: dict(usuario))
    monkeypatch.setattr(P, "modo", lambda: modo)
    # Perfil do cliente sem ajuste: vale o perfil fixo (sem ler disco).
    monkeypatch.setattr(P, "carregar_perfis", lambda slug: {})
    return TestClient(app)


@pytest.mark.parametrize("modo", ["sombra", "valer"])
def test_viewer_barrado_em_todo_metodo(monkeypatch, modo):
    c = _cliente(monkeypatch, VIEWER, modo)
    for m in METODOS:
        r = c.request(m, ROTA, headers=H)
        assert r.status_code == 403, (modo, m, r.status_code)


@pytest.mark.parametrize("modo", ["sombra", "valer"])
def test_operador_passa(monkeypatch, modo):
    c = _cliente(monkeypatch, OPERADOR, modo)
    for m in METODOS:
        assert c.request(m, ROTA, headers=H).status_code == 200, (modo, m)


def test_options_sem_login_nao_chega_no_equipamento(monkeypatch):
    c = _cliente(monkeypatch, OPERADOR, "sombra")
    assert c.options(ROTA).status_code == 401
