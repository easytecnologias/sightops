"""Bilhete curto para abrir o video ao vivo sem cookie (app instalado).

O WebSocket do player (/go2rtc/api/ws) passa pelo nginx auth_request ->
/api/auth/video-ok, que so conhecia o cookie de sessao do navegador. O APK
fala com a API por Bearer e nao tem esse cookie; um WebSocket tambem nao manda
cabecalho Authorization. Por isso o app pede um bilhete (logado) e o poe no
endereco do WebSocket: `?src=<stream>&t=<bilhete>`.

O bilhete vale 60 s, serve para UM stream e UM cliente, e e assinado com a
chave do servidor (SIGHTOPS_SECRET_KEY). Ele vai parar no log de acesso do
nginx (esta na URL) -- por isso e curto e preso ao stream, nunca o token de
sessao.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import threading
import time
from typing import Optional

VALIDADE_S = 60
_CLIENTE = re.compile(r"^[a-z0-9_-]{1,64}$")
# Bilhetes ja usados (assinatura -> expira). Uso unico: o bilhete fica no log de
# acesso do nginx e no do Cloudflare, e quem o lesse la nao pode reabrir o video.
# Um processo uvicorn so (Dockerfile), entao a memoria basta.
_usados: dict = {}
_trava = threading.Lock()


def _chave() -> bytes:
    from app.core.crypto import _load_or_create_key

    # Deriva uma chave so para isto: a chave do cofre nunca e usada direto.
    return hashlib.sha256(b"sightops-video-ticket|" + _load_or_create_key()).digest()


def _assinatura(src: str, cliente: str, expira: int) -> str:
    msg = f"v1|{src}|{cliente}|{expira}".encode("utf-8")
    sig = hmac.new(_chave(), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")


def emitir(src: str, cliente: str, agora: Optional[float] = None) -> str:
    cliente = str(cliente or "").strip().lower()
    if not src or not _CLIENTE.match(cliente):
        raise ValueError("stream ou cliente invalido")
    expira = int((agora if agora is not None else time.time()) + VALIDADE_S)
    return f"{expira}.{cliente}.{_assinatura(src, cliente, expira)}"


def validar(src: str, bilhete: str, agora: Optional[float] = None, consumir: bool = True) -> Optional[str]:
    """Devolve o cliente do bilhete, ou None se ele nao vale para este stream agora.
    Com `consumir`, o bilhete deixa de valer depois da primeira vez."""
    try:
        expira_txt, cliente, sig = str(bilhete or "").split(".", 2)
        expira = int(expira_txt)
    except ValueError:
        return None
    if not src or not _CLIENTE.match(cliente):
        return None
    if expira < int(agora if agora is not None else time.time()):
        return None
    if expira - int(agora if agora is not None else time.time()) > VALIDADE_S + 5:
        return None  # validade maior do que a emitida: forjado
    if not hmac.compare_digest(sig, _assinatura(src, cliente, expira)):
        return None
    if consumir:
        momento = int(agora if agora is not None else time.time())
        with _trava:
            for k in [k for k, v in _usados.items() if v < momento]:
                _usados.pop(k, None)
            if sig in _usados:
                return None
            _usados[sig] = expira
    return cliente
