"""Leitura da camera termica (so GET): matriz de temperatura + fotos.

Caminho de rede igual ao resto do parque: `_base` traduz o IP real para o IP
virtual do conector (vnat). Camera atras de conector isolado so responde la.
"""
from __future__ import annotations

from typing import Any

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from app.services.recorder_xray import _base
from app.services.termico_deteccao import Quadro, ler_quadro

CAMINHO_MATRIZ = "/ISAPI/Thermal/channels/{canal}/thermometry/jpegPicWithAppendData?format=json"


def base_da_camera(host: str, porta: Any = 80, connector_id: str = "") -> str:
    return _base(host, porta, connector_id)


def buscar_quadro(base: str, usuario: str, senha: str, canal: int = 2, timeout: float = 15.0) -> Quadro:
    """Um quadro termico. Levanta ValueError com a causa (credencial recusada,
    medicao desligada, resposta estranha) e deixa erro de rede subir."""
    url = base + CAMINHO_MATRIZ.format(canal=int(canal))
    r = None
    for auth in (HTTPDigestAuth(usuario, senha), HTTPBasicAuth(usuario, senha)):
        r = requests.get(url, auth=auth, timeout=timeout, verify=False)
        if r.status_code not in (401, 403):
            break
    if r is None or r.status_code in (401, 403):
        raise ValueError("a camera recusou a credencial")
    if r.status_code != 200:
        raise ValueError(f"a camera respondeu {r.status_code}: {r.text[:160]!r} (medicao de temperatura ligada?)")
    return ler_quadro(r.content, r.headers.get("Content-Type", ""))
