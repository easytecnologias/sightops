"""Tela Usuarios: ultimo acesso, sessoes abertas, encerrar sessoes e atividade.
Banco de autenticacao em SQLite temporario; so usuarios ficticios."""
from __future__ import annotations

import pytest

from app.services import auth_store as A


@pytest.fixture()
def auth(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("AUTH_DEFAULT_ADMIN_USERNAME", "dono-teste")
    monkeypatch.setenv("AUTH_DEFAULT_ADMIN_PASSWORD", "dono-teste-123")
    monkeypatch.setattr(A, "_SCHEMA_READY", False)
    A.init_auth_db()
    dono = A.authenticate_user("dono-teste", "dono-teste-123")
    A.create_tenant(dono, slug="cliente-a", name="Cliente A", owner_username="dono-a", owner_password="senha-teste-123")
    A.create_tenant(dono, slug="cliente-b", name="Cliente B", owner_username="dono-b", owner_password="senha-teste-123")
    dono_a = A.authenticate_user("dono-a", "senha-teste-123")
    A.create_user(dono_a, username="portaria-a", password="senha-teste-123", role="viewer", full_name="Portaria A")
    A.create_user(dono_a, username="admin-a", password="senha-teste-123", role="admin", full_name="Admin A")
    return {"dono_a": dono_a, "portaria": A.authenticate_user("portaria-a", "senha-teste-123"),
            "admin_a": A.authenticate_user("admin-a", "senha-teste-123"),
            "dono_b": A.authenticate_user("dono-b", "senha-teste-123")}


def _logar(u):
    tok = A.create_access_token(u, label="web")["access_token"]
    A.get_user_by_token(tok)  # marca last_seen_at
    return tok


def test_ultimo_acesso_e_sessoes_so_do_cliente(auth):
    _logar(auth["portaria"])
    _logar(auth["portaria"])
    _logar(auth["dono_b"])
    lista = {u["username"]: u for u in A.users_overview(auth["dono_a"])}
    assert set(lista) == {"dono-a", "portaria-a", "admin-a"}  # nada do cliente B
    assert lista["portaria-a"]["active_sessions"] == 2 and lista["portaria-a"]["last_seen"]
    assert lista["admin-a"]["active_sessions"] == 0 and lista["admin-a"]["last_seen"] == ""


def test_encerrar_sessoes_derruba_o_token(auth):
    tok = _logar(auth["portaria"])
    assert A.revoke_user_sessions(auth["admin_a"], auth["portaria"]["id"])["revoked"] == 1
    assert A.get_user_by_token(tok) is None
    det = A.user_detail(auth["dono_a"], auth["portaria"]["id"])
    assert det["sessions"] == []
    assert any(e["action"] == "user.revoke_sessions" for e in A.user_detail(auth["dono_a"], auth["admin_a"]["id"])["events"])


def test_protecoes(auth):
    with pytest.raises(ValueError):
        A.revoke_user_sessions(auth["portaria"], auth["admin_a"]["id"])  # viewer nao encerra
    with pytest.raises(ValueError):
        A.revoke_user_sessions(auth["admin_a"], auth["admin_a"]["id"])  # a propria: use Sair
    with pytest.raises(ValueError):
        A.revoke_user_sessions(auth["admin_a"], auth["dono_a"]["id"])  # admin nao derruba o dono
    with pytest.raises(ValueError):
        A.user_detail(auth["dono_a"], auth["dono_b"]["id"])  # usuario de outro cliente
    with pytest.raises(ValueError):
        A.revoke_user_sessions(auth["dono_a"], auth["dono_b"]["id"])


def test_sessoes_operando_como_ficam_fora_e_viewer_nao_le(auth, monkeypatch):
    tok = A.create_access_token(auth["admin_a"], label="web")["access_token"]
    with A._conn() as c:
        A._execute(c, "UPDATE auth_tokens SET acting_tenant_id=1 WHERE user_id=?", (auth["admin_a"]["id"],))
    A.get_user_by_token(tok)
    lista = {u["username"]: u for u in A.users_overview(auth["dono_a"])}
    assert lista["admin-a"]["active_sessions"] == 0
    assert A.user_detail(auth["dono_a"], auth["admin_a"]["id"])["sessions"] == []
    with pytest.raises(ValueError):
        A.users_overview(auth["portaria"])
    with pytest.raises(ValueError):
        A.user_detail(auth["portaria"], auth["admin_a"]["id"])


def test_admin_da_plataforma_nao_e_derrubado_pelo_cliente(auth):
    with A._conn() as c:
        A._execute(c, "UPDATE users SET is_platform_admin=1 WHERE id=?", (auth["admin_a"]["id"],))
    _logar(auth["admin_a"])
    with pytest.raises(ValueError):
        A.revoke_user_sessions(auth["dono_a"], auth["admin_a"]["id"])


def test_unico_dono_nao_e_rebaixado(auth):
    dono = auth["dono_a"]
    with pytest.raises(ValueError):
        A.update_user_profile(dono, dono["id"], full_name="Dono", email="", role="admin")
    A.update_user_profile(dono, auth["admin_a"]["id"], full_name="Admin A", email="", role="owner")
    A.update_user_profile(dono, dono["id"], full_name="Dono", email="", role="admin")  # agora ha outro dono
