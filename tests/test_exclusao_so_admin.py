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


# --------------------------------------------------------------------------- autorizacao do administrador

def _app_exclusao(monkeypatch, usuario):
    import dataclasses

    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.delete("/api/access-control/people/{pid}")
    def excluir(pid: str):
        return {"ok": True, "pid": pid}

    @app.post("/api/deployments/recorder-edit")
    def editar():
        if not P.pode_excluir():
            raise P.erro_exige_admin()
        return {"ok": True, "autorizado_por": (P.autorizacao_da_requisicao() or {}).get("admin")}

    settings = dataclasses.replace(get_settings(), auth_enabled=True, auth_required=True)
    app.add_middleware(SEC.ApiAuthMiddleware, settings=settings)
    monkeypatch.setattr(SEC, "get_user_by_token", lambda tok: usuario)
    monkeypatch.setattr(P, "modo", lambda: "sombra")
    return TestClient(app)


OPERADOR = {"id": 21, "username": "op", "role": "operator", "tenant_slug": "cli", "effective_tenant_slug": "cli",
            "effective_enabled_modules": None}
ADMIN = {"id": 2, "username": "chefe", "role": "admin", "tenant_slug": "cli"}
H = {"Authorization": "Bearer x"}


def test_operador_recebe_403_que_pede_senha(monkeypatch):
    c = _app_exclusao(monkeypatch, dict(OPERADOR))
    r = c.delete("/api/access-control/people/9", headers=H)
    assert r.status_code == 403 and r.headers.get(P.CABECALHO_EXIGE_ADMIN) == "1"
    r = c.post("/api/deployments/recorder-edit", headers=H)
    assert r.status_code == 403 and r.headers.get(P.CABECALHO_EXIGE_ADMIN) == "1"


def test_autorizacao_vale_uma_vez_e_so_para_a_mesma_acao(monkeypatch):
    c = _app_exclusao(monkeypatch, dict(OPERADOR))
    cod = P.emitir_autorizacao(ADMIN, OPERADOR, "DELETE", "/api/access-control/people/9")
    # outra pessoa: nao serve (e o codigo e gasto)
    r = c.delete("/api/access-control/people/10", headers={**H, P.CABECALHO_AUTORIZACAO: cod})
    assert r.status_code == 403
    cod = P.emitir_autorizacao(ADMIN, OPERADOR, "DELETE", "/api/access-control/people/9")
    r = c.delete("/api/access-control/people/9", headers={**H, P.CABECALHO_AUTORIZACAO: cod})
    assert r.status_code == 200
    r = c.delete("/api/access-control/people/9", headers={**H, P.CABECALHO_AUTORIZACAO: cod})
    assert r.status_code == 403  # uso unico
    cod = P.emitir_autorizacao(ADMIN, OPERADOR, "POST", "/api/deployments/recorder-edit")
    r = c.post("/api/deployments/recorder-edit", headers={**H, P.CABECALHO_AUTORIZACAO: cod})
    assert r.status_code == 200 and r.json()["autorizado_por"] == "chefe"


def test_autorizacao_nao_passa_para_outro_usuario_nem_viewer(monkeypatch):
    outro = {**OPERADOR, "id": 22}
    cod = P.emitir_autorizacao(ADMIN, OPERADOR, "DELETE", "/api/access-control/people/9")
    c = _app_exclusao(monkeypatch, outro)
    assert c.delete("/api/access-control/people/9", headers={**H, P.CABECALHO_AUTORIZACAO: cod}).status_code == 403
    viewer = {**OPERADOR, "role": "viewer"}
    cod = P.emitir_autorizacao(ADMIN, viewer, "DELETE", "/api/access-control/people/9")
    c = _app_exclusao(monkeypatch, viewer)
    assert c.delete("/api/access-control/people/9", headers={**H, P.CABECALHO_AUTORIZACAO: cod}).status_code == 403


def test_rota_de_autorizar_confere_senha_papel_e_cliente(monkeypatch):
    from types import SimpleNamespace

    from app.api.endpoints import auth as A

    contas = {"chefe": {**ADMIN, "is_platform_admin": False}, "op2": {**ADMIN, "id": 3, "role": "operator"},
              "alheio": {**ADMIN, "id": 4, "tenant_slug": "outro"}}
    monkeypatch.setattr(A, "authenticate_user", lambda u, p: contas.get(u) if p == "certa" else None)
    monkeypatch.setattr(A, "_auditar_acesso", lambda *a, **k: None)
    A._LOGIN_FAILS.clear()
    req = SimpleNamespace(state=SimpleNamespace(current_user=dict(OPERADOR)), headers={}, client=SimpleNamespace(host="1.2.3.4"))

    def pedir(u, p="certa"):
        return A.api_auth_autorizar_exclusao(A.AutorizarExclusaoRequest(username=u, password=p, metodo="DELETE",
                                                                          caminho="/api/access-control/people/9"), req)

    assert pedir("chefe")["autorizado_por"] == "chefe"
    for u, p in (("chefe", "errada"), ("op2", "certa"), ("alheio", "certa")):
        with pytest.raises(HTTPException) as e:
            pedir(u, p)
        assert e.value.status_code == 403


def test_codigo_preso_ao_conteudo(monkeypatch):
    c = _app_exclusao(monkeypatch, dict(OPERADOR))
    certo = '{"acao":"excluir","canal":3}'
    cod = P.emitir_autorizacao(ADMIN, OPERADOR, "POST", "/api/deployments/recorder-edit", P.hash_corpo(certo))
    r = c.post("/api/deployments/recorder-edit", content='{"acao":"excluir","canal":9}',
               headers={**H, P.CABECALHO_AUTORIZACAO: cod, "Content-Type": "application/json"})
    assert r.status_code == 403  # trocou o canal
    cod = P.emitir_autorizacao(ADMIN, OPERADOR, "POST", "/api/deployments/recorder-edit", P.hash_corpo(certo))
    r = c.post("/api/deployments/recorder-edit", content=certo,
               headers={**H, P.CABECALHO_AUTORIZACAO: cod, "Content-Type": "application/json"})
    assert r.status_code == 200


def test_rota_que_ja_era_de_admin_nao_e_autorizavel():
    mw = _mw()
    assert not mw.autorizavel("/api/access-control/devices/d1", "DELETE")
    assert not mw.autorizavel("/api/auth/users/3", "DELETE")
    assert mw.autorizavel("/api/access-control/people/9", "DELETE")
    assert mw.autorizavel("/api/deployments/recorder-edit", "POST")
