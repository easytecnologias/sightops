"""Webhook da Meta: sem App Secret recusa; assinado por um cliente nao entra no
numero de outro; webhook unico do app da plataforma continua valendo. Nada e
enviado para a Meta. So dados ficticios."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import access_control as AC
from app.core import tenant_context as T
from app.services import access_control_notifications as N

CONFIG = {
    "cli-a": {"phone_number_id": "111", "app_secret": "segredo-a"},
    "cli-b": {"phone_number_id": "222", "app_secret": "segredo-b"},
    "cli-sem": {"phone_number_id": "333"},
    "plataforma": {"phone_number_id": "999", "app_secret": "segredo-app"},
}
CORPO = json.dumps({"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "111"}}}]}]}).encode()


def _assinar(segredo, corpo=CORPO):
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


@pytest.fixture()
def webhook(monkeypatch):
    def carregar():
        return {"access_control_whatsapp_notifications": dict(CONFIG.get(T.get_current_tenant_slug()) or {})}

    monkeypatch.setattr(N.db_store, "load_app_settings", carregar)
    monkeypatch.setattr(N, "decrypt", lambda v: v)
    monkeypatch.setattr(N, "tenant_da_plataforma", lambda s: s == "plataforma")
    donos = {"111": "cli-a", "222": "cli-b", "333": "cli-sem", "999": "plataforma"}
    monkeypatch.setattr(AC, "resolver_cliente_por_numero", lambda n: {"tenant": donos[n], "site": ""} if n in donos else {})
    entregues = []

    def processado(payload):
        entregues.append(T.get_current_tenant_slug())
        return {"from_number": ""}

    monkeypatch.setattr(AC, "extract_meta_statuses", lambda p: [])
    monkeypatch.setattr(AC, "extract_meta_inbound", processado)
    app = FastAPI()
    app.include_router(AC.router)
    return TestClient(app), entregues


def _post(c, slug, assinatura, corpo=CORPO):
    return c.post(f"/api/access-control/whatsapp/meta/{slug}", content=corpo,
                  headers={"x-hub-signature-256": assinatura}).json()


def test_sem_app_secret_recusa(webhook):
    c, entregues = webhook
    corpo = CORPO.replace(b"111", b"333")
    assert _post(c, "cli-sem", _assinar("qualquer", corpo), corpo)["ignored"] == "assinatura invalida"
    assert entregues == []


def test_assinatura_errada_recusa(webhook):
    c, entregues = webhook
    assert _post(c, "cli-a", _assinar("outra"))["ignored"] == "assinatura invalida"
    assert entregues == []


def test_cliente_b_nao_entra_no_numero_do_a(webhook):
    c, entregues = webhook
    assert _post(c, "cli-b", _assinar("segredo-b"))["ignored"] == "numero de outro cliente"
    assert entregues == []


def test_numero_do_proprio_cliente_passa(webhook):
    c, entregues = webhook
    assert _post(c, "cli-a", _assinar("segredo-a"))["ok"] is True
    assert entregues == ["cli-a"]


def test_webhook_unico_da_plataforma_entrega_ao_dono_do_numero(webhook):
    c, entregues = webhook
    assert "ignored" not in _post(c, "plataforma", _assinar("segredo-app"))
    assert entregues == ["cli-a"]


def test_rota_put_aceita_app_secret():
    assert "app_secret" in AC.AccessWhatsappConfigRequest.model_fields


def test_secret_salvo_em_site_fica_onde_o_webhook_procura(monkeypatch):
    guardado = {"access_control_whatsapp_notifications": {"enabled": True}}
    monkeypatch.setattr(N.db_store, "load_app_settings", lambda: guardado)
    monkeypatch.setattr(N.db_store, "save_app_settings", lambda s: guardado.update(s))
    monkeypatch.setattr(N, "encrypt", lambda v: "cifrado:" + v)
    monkeypatch.setattr(N, "decrypt", lambda v: v)
    monkeypatch.setattr(N, "get_access_whatsapp_config", lambda site: {})
    N.save_access_whatsapp_config({"site": "Escola 1", "provider": "cloud_api", "enabled": True, "app_secret": "novo"})
    assert guardado["access_control_whatsapp_notifications"]["app_secret"] == "cifrado:novo"
    assert guardado["access_control_whatsapp_notifications"]["enabled"] is True


def test_tenant_da_plataforma_olha_o_banco(tmp_path, monkeypatch):
    from app.services import auth_store as A

    monkeypatch.setenv("AUTH_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("AUTH_DEFAULT_ADMIN_USERNAME", "dono-teste")
    monkeypatch.setenv("AUTH_DEFAULT_ADMIN_PASSWORD", "dono-teste-123")
    monkeypatch.setattr(A, "_SCHEMA_READY", False)
    A.init_auth_db()
    dono = A.authenticate_user("dono-teste", "dono-teste-123")
    A.create_tenant(dono, slug="cliente-a", name="Cliente A", owner_username="dono-a", owner_password="senha-teste-123")
    assert A.tenant_da_plataforma(dono["tenant_slug"]) is True
    assert A.tenant_da_plataforma("cliente-a") is False
    assert A.tenant_da_plataforma("nao-existe") is False
