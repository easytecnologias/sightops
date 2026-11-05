"""E2: erro interno com codigo e 422 em portugues (app/core/erros.py)."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core import erros
from app.core.observability import RequestContextMiddleware


class _Corpo(BaseModel):
    nome: str
    porta: int


def _app() -> FastAPI:
    app = FastAPI()
    erros.instalar(app)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/explode")
    def explode():
        raise RuntimeError("segredo-interno")

    @app.post("/corpo")
    def corpo(c: _Corpo):
        return {"ok": True}

    return app


def test_excecao_vira_json_com_codigo_e_log(caplog):
    client = TestClient(_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="app.erros"):
        r = client.get("/explode", headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 500
    assert r.json()["detail"] == "Erro interno. Código: abc-123"
    assert "segredo-interno" not in r.text
    assert r.headers.get("X-Request-ID") == "abc-123"
    assert any("abc-123" in rec.getMessage() and rec.exc_info for rec in caplog.records)


def test_validacao_em_portugues_com_lista_original():
    client = TestClient(_app())
    r = client.post("/corpo", json={"porta": "x"})
    assert r.status_code == 422
    corpo = r.json()
    assert isinstance(corpo["detail"], str)
    assert "O campo 'nome' é obrigatório." in corpo["detail"]
    assert "O campo 'porta' precisa ser número inteiro." in corpo["detail"]
    assert isinstance(corpo["erros"], list) and len(corpo["erros"]) == 2


def test_json_invalido():
    client = TestClient(_app())
    r = client.post("/corpo", content=b"{nao json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert "JSON válido" in r.json()["detail"]


def test_resumo_limita_quantidade():
    lista = [{"type": "missing", "loc": ["body", f"c{i}"], "msg": "x"} for i in range(8)]
    texto = erros.resumir_validacao(lista)
    assert texto.startswith("Dados inválidos: ")
    assert "(e mais 3 erro(s))" in texto
    assert erros.resumir_validacao([]) == "Dados inválidos."
