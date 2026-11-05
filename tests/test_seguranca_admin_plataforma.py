"""Owner do cliente onde o admin da plataforma mora nao altera esse admin.
Banco de autenticacao em SQLite temporario; so usuarios ficticios."""
from __future__ import annotations

import pytest

from app.services import auth_store as A

SENHA = "senha-teste-123"


@pytest.fixture()
def auth(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("AUTH_DEFAULT_ADMIN_USERNAME", "bootstrap-teste")
    monkeypatch.setenv("AUTH_DEFAULT_ADMIN_PASSWORD", SENHA)
    monkeypatch.setattr(A, "_SCHEMA_READY", False)
    A.init_auth_db()
    inicial = A.authenticate_user("bootstrap-teste", SENHA)
    # Criar usuario real desativa o bootstrap: o admin da plataforma do teste e
    # um usuario comum promovido, como em producao.
    A.create_user(inicial, username="plataforma", password=SENHA, role="owner", full_name="Plataforma")
    A.create_user(inicial, username="dono-comum", password=SENHA, role="owner", full_name="Dono Comum")
    A.create_user(inicial, username="colega", password=SENHA, role="viewer", full_name="Colega")
    with A._conn() as c:
        A._execute(c, "UPDATE users SET is_platform_admin=1 WHERE username=?", ("plataforma",))
        A._execute(c, "UPDATE users SET is_platform_admin=0 WHERE username<>?", ("plataforma",))
    plataforma = A.authenticate_user("plataforma", SENHA)
    assert plataforma["is_platform_admin"]
    return {"plataforma": plataforma, "dono": A.authenticate_user("dono-comum", SENHA),
            "colega": A.authenticate_user("colega", SENHA)}


def _acoes(ator, alvo_id):
    return [
        lambda: A.update_user_password(ator, alvo_id, "senha-nova-123"),
        lambda: A.update_user_status(ator, alvo_id, False),
        lambda: A.rename_user(ator, alvo_id, "novo-login"),
        lambda: A.update_user_profile(ator, alvo_id, full_name="Trocado", email="", role="viewer"),
        lambda: A.delete_user(ator, alvo_id),
    ]


def test_owner_comum_nao_altera_admin_da_plataforma(auth):
    alvo = int(auth["plataforma"]["id"])
    assert not auth["dono"].get("is_platform_admin")
    for acao in _acoes(auth["dono"], alvo):
        with pytest.raises(ValueError, match="admin da plataforma"):
            acao()
    assert A.authenticate_user("plataforma", SENHA) is not None  # senha e login intactos


def test_owner_comum_continua_alterando_colega(auth):
    alvo = int(auth["colega"]["id"])
    A.update_user_password(auth["dono"], alvo, "senha-nova-123")
    assert A.authenticate_user("colega", "senha-nova-123") is not None


def test_admin_da_plataforma_altera_a_si_e_aos_outros(auth):
    A.update_user_password(auth["plataforma"], int(auth["plataforma"]["id"]), "senha-nova-123")
    assert A.authenticate_user("plataforma", "senha-nova-123") is not None
    A.update_user_password(auth["plataforma"], int(auth["dono"]["id"]), "senha-outra-123")
    assert A.authenticate_user("dono-comum", "senha-outra-123") is not None
