from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core import metricas_http
from app.core.settings import AppSettings


# Sem esta lista o `extra=` do log era descartado em silencio: o middleware media
# rota e tempo de toda requisicao e nada disso chegava ao log.
_CAMPOS_EXTRAS = ("method", "path", "status_code", "elapsed_ms")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = getattr(record, "request_id", "")
        if request_id:
            payload["request_id"] = request_id
        for campo in _CAMPOS_EXTRAS:
            valor = getattr(record, campo, None)
            if valor is not None:
                payload[campo] = valor
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(settings: AppSettings) -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=settings.log_level)
        root = logging.getLogger()

    formatter: logging.Formatter
    if settings.log_json:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    for handler in root.handlers:
        handler.setFormatter(formatter)
        handler.setLevel(settings.log_level)
    root.setLevel(settings.log_level)


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, logger_name: str = "app.http") -> None:
        super().__init__(app)
        self.logger = logging.getLogger(logger_name)

    def _medir(self, request: Request, status: int, elapsed_ms: float) -> str:
        """Devolve o molde da rota. O log leva o molde, nunca `request.url.path`:
        ha rota com token no caminho (foto do acesso, link assinado do termico)."""
        rota = metricas_http.nome_da_rota(request.scope)
        # Medir nunca pode derrubar a requisicao que esta sendo medida.
        try:
            metricas_http.registrar(request.method, rota, status, elapsed_ms)
        except Exception:
            self.logger.exception("metrica_http_falhou")
        return rota

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        start = time.perf_counter()
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            rota = self._medir(request, 500, elapsed_ms)
            self.logger.exception(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": rota,
                    "elapsed_ms": elapsed_ms,
                },
            )
            raise

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        rota = self._medir(request, response.status_code, elapsed_ms)
        self.logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": rota,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
            },
        )
        return response
