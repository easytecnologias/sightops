"""Onde so se espera IP, nome e recusado (DNS rebinding), e a conexao com o
equipamento nao segue redirect para outro destino."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.endpoints import cameras as C
from app.api.endpoints import maintenance as M
from app.api.endpoints import network_tools as NT
from app.services.camsnapshot import device_info as DI
from test_destino_nome import _ClienteHttp, rebinding  # noqa: F401  (fixture)
from test_destino_permitido import rede  # noqa: F401  (fixture)


def test_caminho_de_video_recusa_nome(rede):
    with pytest.raises(HTTPException) as exc:
        M._conferir_destinos([("cam.atacante.example", "")])
    assert exc.value.status_code == 400


def test_ping_recusa_nome(rede):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(C.api_cameras_ping(ip="cam.atacante.example"))
    assert exc.value.status_code == 400


def test_ping_many_recusa_nome_por_linha(rede, monkeypatch):
    async def _ping(**kw):
        pytest.fail("pingou nome")

    monkeypatch.setattr(C, "ping_with_cache", _ping)
    monkeypatch.setattr(C, "_persist_camera_statuses", lambda d: {})
    req = C.PingBatchRequest(items=[C.PingBatchItem(ip="cam.atacante.example")])
    res = asyncio.run(C.api_cameras_ping_many(req))
    assert res["results"][0]["sem_rota"]


def test_camera_sem_redirect(monkeypatch):
    pedidos = []
    monkeypatch.setattr(DI.requests, "get", lambda url, **kw: pedidos.append(kw) or None)
    DI._try_get("http://192.168.10.5/x", "admin", "x", 2)
    assert pedidos[0]["allow_redirects"] is False


def test_http_com_nome_em_maiusculas_usa_o_ip_aprovado(rebinding, monkeypatch):
    _ClienteHttp.pedidos = []
    monkeypatch.setattr(NT.httpx, "AsyncClient", _ClienteHttp)
    asyncio.run(NT.api_network_tools_run({"test": "http", "targets": "http://CDN.Exemplo.test:8080/x"}))
    assert _ClienteHttp.pedidos[0][0] == "http://8.8.8.8:8080/x"
