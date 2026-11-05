"""Rotas que alcancam todos os clientes (backup do data/ inteiro, banco):
so o admin da plataforma. Admin/owner de cliente toma 403. So dados ficticios."""
from __future__ import annotations

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import permissions as P
from app.core import security as SEC
from app.core.settings import get_settings

H = {"Authorization": "Bearer x"}
ADMIN_CLIENTE = {"id": 2, "username": "admin-a", "role": "admin", "tenant_slug": "cli",
                 "effective_tenant_slug": "cli", "effective_enabled_modules": None}
DONO_CLIENTE = {**ADMIN_CLIENTE, "id": 3, "username": "dono-a", "role": "owner"}
PLATAFORMA = {**ADMIN_CLIENTE, "id": 1, "username": "plataforma", "role": "owner", "is_platform_admin": True}


def _cliente(monkeypatch, usuario, rotas):
    app = FastAPI()
    for metodo, caminho in rotas:
        app.add_api_route(caminho, lambda: {"ok": True}, methods=[metodo])
    settings = dataclasses.replace(get_settings(), auth_enabled=True, auth_required=True)
    app.add_middleware(SEC.ApiAuthMiddleware, settings=settings)
    monkeypatch.setattr(SEC, "get_user_by_token", lambda tok: dict(usuario))
    monkeypatch.setattr(P, "modo", lambda: "sombra")
    return TestClient(app)


BACKUP = [("GET", "/api/backup/export"), ("POST", "/api/backup/import")]


@pytest.mark.parametrize("usuario", [ADMIN_CLIENTE, DONO_CLIENTE])
def test_backup_negado_para_cliente(monkeypatch, usuario):
    c = _cliente(monkeypatch, usuario, BACKUP)
    for metodo, caminho in BACKUP:
        r = c.request(metodo, caminho, headers=H)
        assert r.status_code == 403, (metodo, caminho, r.status_code)


def test_backup_liberado_para_plataforma(monkeypatch):
    c = _cliente(monkeypatch, PLATAFORMA, BACKUP)
    for metodo, caminho in BACKUP:
        r = c.request(metodo, caminho, headers=H)
        assert r.status_code == 200, (metodo, caminho, r.status_code)


def test_backup_export_nao_aceita_token_na_url():
    mw = SEC.ApiAuthMiddleware(FastAPI(), get_settings())
    assert not mw._query_token_allowed("/api/backup/export", "GET")
