"""Historico de acoes (Configuracoes > Historico): o que entra, nome em
portugues, sem senha, e cada cliente so ve o dele. So dados ficticios."""
from __future__ import annotations

import json

import pytest

from app.services import auth_store as A
from app.services import historico_service as H


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
    A.create_user(dono_a, username="op-a", password="senha-teste-123", role="operator", full_name="Operador A")
    # grava na hora (sem a thread de fundo)
    fila = []
    monkeypatch.setattr(H, "_garantir_thread", lambda: None)
    monkeypatch.setattr(H._fila, "put_nowait", fila.append)
    return {"dono_a": dono_a, "op_a": A.authenticate_user("op-a", "senha-teste-123"),
            "dono_b": A.authenticate_user("dono-b", "senha-teste-123"), "fila": fila}


def _gravar(auth):
    H.gravar_lote(auth["fila"])
    auth["fila"].clear()


def test_ruido_fica_de_fora():
    assert H.registravel("POST", "/api/cameras/reboot")
    assert H.registravel("DELETE", "/api/access-control/people/9")
    for m, p in [("GET", "/api/cameras/list"), ("POST", "/api/cameras/ping_many"), ("POST", "/api/maintenance/web/10.0.0.1/x"),
                 ("POST", "/api/maintenance/stream_register/10.0.0.1"), ("POST", "/api/auth/login"),
                 ("POST", "/api/connectors/agent/heartbeat"), ("POST", "/api/network/tools/run")]:
        assert not H.registravel(m, p), (m, p)


def test_nome_em_portugues_e_alvo_sem_senha(auth):
    corpo = json.dumps({"ip": "10.200.0.15", "user": "admin", "password": "segredo", "channel": 3}).encode()
    H.registrar(auth["op_a"], "POST", "/api/cameras/reboot", "/api/cameras/reboot", 200, corpo=corpo, ip="1.2.3.4")
    H.registrar(auth["op_a"], "DELETE", "/api/access-control/people/77", "/api/access-control/people/{person_id}", 403,
                path_params={"person_id": "77"})
    H.registrar(auth["op_a"], "DELETE", "/api/connectors/c9", "/api/connectors/{connector_id}", 200,
                path_params={"connector_id": "c9"}, autorizado_por="dono-a")
    _gravar(auth)
    ev = H.consultar(auth["dono_a"])["eventos"]
    acoes = [e for e in ev if e["action"].startswith("acao")]
    assert [e["action"] for e in acoes] == ["acao.exclusao", "acao.negada", "acao"]
    reboot = acoes[2]
    d = json.loads(reboot["detail_json"])
    assert d["r"] == "Reiniciou câmera" and "10.200.0.15" in reboot["resource_id"] and "canal 3" in reboot["resource_id"]
    assert "segredo" not in json.dumps(acoes)
    assert json.loads(acoes[0]["detail_json"])["autorizado_por"] == "dono-a"
    assert acoes[0]["username"] == "op-a"


def test_cada_cliente_ve_so_o_dele_e_filtros(auth):
    H.registrar(auth["op_a"], "POST", "/api/cameras/reboot", "/api/cameras/reboot", 200)
    H.registrar(auth["dono_b"], "POST", "/api/nvr/reboot", "/api/nvr/reboot", 200)
    _gravar(auth)
    a = [json.loads(e["detail_json"]).get("r") for e in H.consultar(auth["dono_a"], tipo="cameras")["eventos"]]
    b = [json.loads(e["detail_json"]).get("r") for e in H.consultar(auth["dono_b"], tipo="gravadores")["eventos"]]
    assert a == ["Reiniciou câmera"] and b == ["Reiniciou NVR"]
    assert not H.consultar(auth["dono_a"], tipo="gravadores")["eventos"]
    assert H.consultar(auth["dono_a"], usuario_id=auth["op_a"]["id"], tipo="cameras")["eventos"]
    assert not H.consultar(auth["dono_a"], usuario_id=auth["dono_a"]["id"], tipo="cameras")["eventos"]
    assert H.consultar(auth["dono_a"], q="reiniciou")["eventos"]
    with pytest.raises(ValueError):
        H.consultar(auth["dono_a"], de="21/10/2026")


def test_paginacao(auth):
    for _ in range(5):
        H.registrar(auth["op_a"], "POST", "/api/cameras/reboot", "/api/cameras/reboot", 200)
    _gravar(auth)
    p1 = H.consultar(auth["dono_a"], tipo="cameras", limite=3)
    assert len(p1["eventos"]) == 3 and p1["mais"]
    p2 = H.consultar(auth["dono_a"], tipo="cameras", limite=3, antes_id=p1["proximo"])
    assert len(p2["eventos"]) == 2 and not p2["mais"]


def test_rota_sem_rotulo_usa_o_modulo():
    assert H.descrever("POST", "/api/olt/registry/{olt_id}/sync", "/api/olt/registry/1/sync") == "Sincronizou OLT"
    assert H.descrever("POST", "/api/dvr/imgbb/upload", "/api/dvr/imgbb/upload").startswith("Alterou em ")


def test_historico_e_so_de_admin():
    from fastapi import FastAPI

    from app.core import security as SEC
    from app.core.settings import get_settings

    mw = SEC.ApiAuthMiddleware(FastAPI(), get_settings())
    assert mw._match_role_rule("/api/auth/historico", "GET") == "admin"


def test_middleware_registra_acao_e_tentativa_barrada(monkeypatch):
    import dataclasses

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core import permissions as P
    from app.core import security as SEC
    from app.core.settings import get_settings

    app = FastAPI()

    @app.post("/api/cameras/reboot")
    def reboot(payload: dict):
        return {"ok": True}

    @app.delete("/api/access-control/people/{person_id}")
    def excluir(person_id: str):
        return {"ok": True}

    @app.get("/api/cameras/list")
    def listar():
        return {"ok": True}

    settings = dataclasses.replace(get_settings(), auth_enabled=True, auth_required=True)
    app.add_middleware(SEC.ApiAuthMiddleware, settings=settings)
    op = {"id": 5, "username": "op", "role": "operator", "tenant_slug": "x", "effective_tenant_slug": "x",
          "effective_enabled_modules": None}
    monkeypatch.setattr(SEC, "get_user_by_token", lambda tok: op)
    monkeypatch.setattr(P, "modo", lambda: "sombra")
    vistos = []
    monkeypatch.setattr(H, "registrar", lambda user, method, path, modelo, status, **kw: vistos.append((method, modelo, status, kw.get("path_params"), kw.get("corpo"))))
    c = TestClient(app)
    hdr = {"Authorization": "Bearer x"}
    assert c.post("/api/cameras/reboot", json={"ip": "10.0.0.9"}, headers=hdr).status_code == 200
    assert c.delete("/api/access-control/people/42", headers=hdr).status_code == 403
    assert c.get("/api/cameras/list", headers=hdr).status_code == 200
    assert vistos[0][:3] == ("POST", "/api/cameras/reboot", 200) and b"10.0.0.9" in vistos[0][4]
    assert vistos[1][:3] == ("DELETE", "/api/access-control/people/{person_id}", 403)
    assert len(vistos) == 2  # leitura nao entra
