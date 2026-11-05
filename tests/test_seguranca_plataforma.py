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


BANCO = [("POST", "/api/db/init"), ("POST", "/api/db/migrate"), ("POST", "/api/db/storage/migrate"),
         ("POST", "/api/auth/storage/migrate"), ("POST", "/api/system/bootstrap")]


@pytest.mark.parametrize("usuario", [ADMIN_CLIENTE, DONO_CLIENTE])
def test_banco_negado_para_cliente(monkeypatch, usuario):
    c = _cliente(monkeypatch, usuario, BANCO)
    for metodo, caminho in BANCO:
        r = c.request(metodo, caminho, headers=H)
        assert r.status_code == 403, (metodo, caminho, r.status_code)


def test_banco_liberado_para_plataforma(monkeypatch):
    c = _cliente(monkeypatch, PLATAFORMA, BANCO)
    for metodo, caminho in BANCO:
        r = c.request(metodo, caminho, headers=H)
        assert r.status_code == 200, (metodo, caminho, r.status_code)


def test_handler_auth_storage_migrate_exige_plataforma(monkeypatch):
    from fastapi import HTTPException

    from app.api.endpoints import auth as AUTH

    # Nunca migrar de verdade no teste, nem quando a trava falha.
    monkeypatch.setattr(AUTH, "migrate_auth_storage", lambda **kw: {"ok": True, "migrou": True})
    req = AUTH.AuthStorageMigrateRequest(source_backend="sqlite", target_backend="postgres", force=True)
    with pytest.raises(HTTPException) as e:
        AUTH.api_auth_storage_migrate(req, user=dict(DONO_CLIENTE))
    assert e.value.status_code == 403
