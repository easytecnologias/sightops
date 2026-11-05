"""Pagina web do equipamento pelo proxy: nao alcanca a API do painel (CSP com
caminho + COOP) e nao grava cookie fora da pasta dela. Nenhum equipamento e
chamado: fetch_device e trocado por uma resposta ficticia."""
from __future__ import annotations

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from requests.cookies import create_cookie

from app.api.endpoints import maintenance as M

IP = "10.0.0.9"
RAIZ = f"/api/maintenance/web/{IP}/"


def _resposta_falsa(cookies):
    r = requests.Response()
    r.status_code = 200
    r._content = b"<html><head></head><body>camera</body></html>"
    r.headers["Content-Type"] = "text/html"
    if cookies:
        r.headers["Set-Cookie"] = ", ".join(f"{c.name}={c.value}; path=/" for c in cookies)
        for c in cookies:
            r.cookies.set_cookie(c)
    return r


def _cliente(monkeypatch, cookies=()):
    monkeypatch.setattr(M, "_camera_web_target_url", lambda ip, path, q: f"http://{ip}/{path}")
    monkeypatch.setattr(M, "web_liberada_para", lambda user, ip: (True, ""))
    monkeypatch.setattr(M, "resolve_camera_password", lambda ip, u, p: ("admin", "x"))
    monkeypatch.setattr(M, "_reach", lambda ip: ip)
    monkeypatch.setattr(M, "_seed_web_proxy_scheme_from_disk", lambda ip: None)
    monkeypatch.setattr(M, "_persist_web_proxy_scheme", lambda ip, s: None)
    monkeypatch.setattr(M, "_device_http_port", lambda ip: 80)
    monkeypatch.setattr(M, "fetch_device", lambda *a, **kw: _resposta_falsa(list(cookies)))
    app = FastAPI()
    app.include_router(M.router)
    return TestClient(app)


def test_csp_prende_a_pagina_na_pasta_do_equipamento(monkeypatch):
    r = _cliente(monkeypatch).get(RAIZ, headers={"Host": "painel.exemplo.com.br"})
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy", "")
    for diretiva in ("connect-src", "frame-src", "worker-src", "object-src", "form-action", "base-uri"):
        assert f"{diretiva} painel.exemplo.com.br{RAIZ}" in csp, (diretiva, csp)
    assert r.headers.get("cross-origin-opener-policy") == "same-origin"


def test_host_estranho_nao_injeta_no_csp(monkeypatch):
    r = _cliente(monkeypatch).get(RAIZ, headers={"Host": "a.com; script-src *"})
    csp = r.headers.get("content-security-policy", "")
    assert "script-src" not in csp and "connect-src 'self'" in csp


def test_set_cookie_do_equipamento_fica_na_pasta_dele(monkeypatch):
    cookies = [create_cookie("WebSession", "abc123", path="/"),
               create_cookie("sightops_session", "roubado", path="/")]
    r = _cliente(monkeypatch, cookies).get(RAIZ)
    valores = r.headers.get_list("set-cookie")
    assert len(valores) == 1, valores
    assert valores[0].startswith("WebSession=abc123;") and f"Path={RAIZ}" in valores[0]
    assert "Path=/;" not in valores[0] and "Domain" not in valores[0]
    assert all("sightops_session" not in v for v in valores)


def test_service_worker_do_equipamento_recusado(monkeypatch):
    r = _cliente(monkeypatch).get(RAIZ + "sw.js", headers={"Service-Worker": "script"})
    assert r.status_code == 403


def test_redirect_da_camera_nao_volta_para_a_api_do_painel():
    painel = "painel.exemplo.com.br"
    for destino in (f"https://{painel}/api/auth/agent-token", f"HTTPS://{painel.upper()}/api/auth/agent-token",
                    f"//{painel}/api/auth/agent-token", f"https:\\\\{painel}/api/auth/agent-token",
                    f"\\\\{painel}/api/auth/agent-token", f"ht\ttps://{painel}/api/auth/agent-token",
                    f"https://{painel}:443/api/auth/agent-token"):
        assert M._web_proxy_location_segura(destino, f"{painel}:443", IP) == RAIZ, destino
    assert M._web_proxy_location_segura(RAIZ + "login", painel, IP) == RAIZ + "login"
    assert M._web_proxy_location_segura("login.asp", painel, IP) == "login.asp"
    assert M._web_proxy_location_segura("https://outro.exemplo/x", painel, IP) == "https://outro.exemplo/x"
