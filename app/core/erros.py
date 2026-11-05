"""Erros que chegam na tela do cliente.

Antes: excecao nao tratada virava "Internal Server Error" (texto puro, sem
como achar no log) e erro de validacao virava uma lista de objetos que a tela
mostrava como "[object Object]". Aqui:

- Exception -> 500 JSON {"detail": "Erro interno. Codigo: <request_id>"} e o
  traceback no log com o mesmo request_id (o RequestContextMiddleware gera).
- RequestValidationError -> 422 com `detail` em portugues (uma frase) e a
  lista original em `erros`, para quem precisar do detalhe tecnico.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.erros")

_ORIGENS = {"body", "query", "path", "header", "cookie"}

_FRASES = {
    "missing": "é obrigatório",
    "string_type": "precisa ser texto",
    "int_type": "precisa ser número inteiro",
    "int_parsing": "precisa ser número inteiro",
    "int_from_float": "precisa ser número inteiro",
    "float_type": "precisa ser número",
    "float_parsing": "precisa ser número",
    "bool_type": "precisa ser sim ou não",
    "bool_parsing": "precisa ser sim ou não",
    "list_type": "precisa ser uma lista",
    "dict_type": "precisa ser um objeto",
    "model_type": "está em formato inválido",
    "json_invalid": "não é um JSON válido",
    "enum": "tem um valor que não está entre as opções",
    "literal_error": "tem um valor que não está entre as opções",
    "date_parsing": "precisa ser uma data válida",
    "date_from_datetime_parsing": "precisa ser uma data válida",
    "datetime_parsing": "precisa ser data e hora válidas",
    "datetime_from_date_parsing": "precisa ser data e hora válidas",
    "uuid_parsing": "precisa ser um identificador válido",
    "extra_forbidden": "não é aceito aqui",
}


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", "") or request.headers.get("x-request-id") or ""
    if not rid:
        rid = str(uuid.uuid4())
        request.state.request_id = rid
    return str(rid)


def _campo(loc: Any) -> str:
    partes = [str(p) for p in (loc or ()) if str(p) not in _ORIGENS]
    return ".".join(partes)


def _frase_de(erro: dict) -> str:
    tipo = str(erro.get("type") or "")
    ctx = erro.get("ctx") or {}
    if tipo in _FRASES:
        texto = _FRASES[tipo]
    elif tipo == "string_too_short":
        texto = f"precisa ter pelo menos {ctx.get('min_length', '?')} caractere(s)"
    elif tipo == "string_too_long":
        texto = f"pode ter no máximo {ctx.get('max_length', '?')} caractere(s)"
    elif tipo in ("greater_than", "greater_than_equal"):
        limite = ctx.get("gt", ctx.get("ge", "?"))
        texto = f"precisa ser {'maior que' if tipo == 'greater_than' else 'no mínimo'} {limite}"
    elif tipo in ("less_than", "less_than_equal"):
        limite = ctx.get("lt", ctx.get("le", "?"))
        texto = f"precisa ser {'menor que' if tipo == 'less_than' else 'no máximo'} {limite}"
    elif tipo == "value_error":
        texto = str(erro.get("msg") or "").removeprefix("Value error, ").strip() or "tem um valor inválido"
    else:
        texto = str(erro.get("msg") or "tem um valor inválido")
    campo = _campo(erro.get("loc"))
    if tipo == "json_invalid" or not campo:
        return f"O corpo da requisição {texto}." if tipo in ("json_invalid", "missing") else f"{texto[:1].upper()}{texto[1:]}."
    return f"O campo '{campo}' {texto}."


def resumir_validacao(erros: list[dict]) -> str:
    """Junta os erros do pydantic numa frase so, em portugues."""
    frases: list[str] = []
    for erro in erros or []:
        frase = _frase_de(erro if isinstance(erro, dict) else {"msg": str(erro)})
        if frase not in frases:
            frases.append(frase)
    if not frases:
        return "Dados inválidos."
    mostradas = frases[:5]
    resto = len(frases) - len(mostradas)
    texto = "Dados inválidos: " + " ".join(mostradas)
    if resto > 0:
        texto += f" (e mais {resto} erro(s))"
    return texto


async def _erro_de_validacao(request: Request, exc: RequestValidationError) -> JSONResponse:
    erros = jsonable_encoder(exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": resumir_validacao(erros), "erros": erros},
    )


async def _erro_interno(request: Request, exc: Exception) -> JSONResponse:
    rid = _request_id(request)
    logger.exception(
        "erro_interno request_id=%s %s %s",
        rid,
        request.method,
        request.url.path,
        exc_info=exc,
        extra={"request_id": rid},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"Erro interno. Código: {rid}", "request_id": rid},
        headers={"X-Request-ID": rid},
    )


def instalar(app: FastAPI) -> None:
    """Registra os tratadores de erro no app."""
    app.add_exception_handler(RequestValidationError, _erro_de_validacao)
    app.add_exception_handler(Exception, _erro_interno)
