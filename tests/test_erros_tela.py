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


# --- E3: tradutor de erro de rede ------------------------------------------

def test_tradutor_reconhece_os_erros_de_rede():
    import requests

    cru = ("HTTPConnectionPool(host='10.0.0.1', port=80): Max retries exceeded with url: / "
           "(Caused by NewConnectionError('Failed to establish a new connection: [Errno 113] No route to host'))")
    assert "IP virtual" in erros.traduzir_erro_rede(Exception(cru), "o gravador")
    assert "recusou a conexão" in erros.traduzir_erro_rede(ConnectionRefusedError(111, "Connection refused"))
    assert "não respondeu a tempo" in erros.traduzir_erro_rede(requests.ReadTimeout("Read timed out."), "a câmera")
    assert "usuário ou a senha" in erros.traduzir_erro_rede(RuntimeError("DVR respondeu HTTP 401 em RPC_Loadfile."))
    assert erros.traduzir_erro_rede(ValueError("canal 3 inexistente")) is None
    assert erros.traduzir_erro_rede(RuntimeError("porta 4010 fechada")) is None


def test_tradutor_olha_a_causa_encadeada():
    try:
        try:
            raise OSError(113, "No route to host")
        except OSError as base:
            raise RuntimeError("Falha ao baixar do DVR (loadfile e RPC): http://10.0.0.1") from base
    except RuntimeError as exc:
        assert erros.traduzir_erro_rede(exc, "o gravador").startswith("Sem rota até o gravador")


def test_frase_mantem_mensagem_propria_e_loga_o_tecnico(caplog):
    with caplog.at_level(logging.WARNING, logger="app.erros"):
        frase = erros.frase_erro_equipamento(Exception("Read timed out. (read timeout=5)"), "o gravador", "falha: ")
    assert frase.startswith("O gravador não respondeu a tempo")
    assert any("read timeout=5" in rec.getMessage() for rec in caplog.records)
    assert erros.frase_erro_equipamento(ValueError("canal invalido"), prefixo="Erro: ", registrar=False) == "Erro: canal invalido"


def test_502_vira_424_em_todo_api():
    import asyncio
    from fastapi import HTTPException
    from starlette.requests import Request
    import app.main as m

    def req(path):
        return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""})

    r = asyncio.run(m._erro_do_leitor_sem_502(req("/api/dvr/status"), HTTPException(502, "Sem rota até o gravador.")))
    assert r.status_code == 424 and "Sem rota".encode() in r.body
    assert asyncio.run(m._erro_do_leitor_sem_502(req("/api/olt/x"), HTTPException(500, "x"))).status_code == 500
