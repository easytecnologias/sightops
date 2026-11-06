"""Leitura da camera termica (so GET): matriz de temperatura + fotos.

Caminho de rede igual ao resto do parque: `_base` traduz o IP real para o IP
virtual do conector (vnat). Camera atras de conector isolado so responde la.
"""
from __future__ import annotations

import re
from typing import Any, Dict

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from app.services.recorder_xray import _base
from app.services.termico_deteccao import Quadro, ler_quadro

CAMINHO_MATRIZ = "/ISAPI/Thermal/channels/{canal}/thermometry/jpegPicWithAppendData?format=json"


def base_da_camera(host: str, porta: Any = 80, connector_id: str = "") -> str:
    return _base(host, porta, connector_id)


def _put_xml(url: str, usuario: str, senha: str, corpo: str, timeout: float = 10.0) -> requests.Response:
    return requests.put(url, data=corpo.encode("utf-8"), auth=HTTPDigestAuth(usuario, senha), timeout=timeout,
                        verify=False, headers={"Content-Type": "application/xml"})


def preparar_medicao(base: str, usuario: str, senha: str, canal: int = 2) -> Dict[str, Any]:
    """Liga a medicao de temperatura e tira a foto colorida de cada leitura
    (1,5 MB vira 200 KB, medido na CAM P 03). ESCREVE na camera: so chamar por
    pedido explicito (botao Vigiar). So toca no campo que precisa mudar."""
    auth = HTTPDigestAuth(usuario, senha)
    feito: Dict[str, Any] = {"medicao": "ja_ligada", "foto_colorida": "ja_desligada"}
    url = f"{base}/ISAPI/Thermal/channels/{int(canal)}/thermometry/basicParam"
    atual = requests.get(url, auth=auth, timeout=10, verify=False)
    if atual.status_code != 200:
        raise ValueError(f"nao li a medicao da camera (HTTP {atual.status_code})")
    # So o primeiro <enabled> e o da medicao: os outros sao de sub-blocos
    # (saidas de alarme, filtros) e nao podem mudar.
    primeiro = re.search(r"<enabled>(true|false)</enabled>", atual.text)
    if primeiro is None:
        raise ValueError("a camera nao informou se a medicao esta ligada")
    if primeiro.group(1) == "false":
        r = _put_xml(url, usuario, senha, atual.text[:primeiro.start()] + "<enabled>true</enabled>" + atual.text[primeiro.end():])
        if r.status_code != 200:
            raise ValueError(f"a camera recusou ligar a medicao (HTTP {r.status_code})")
        feito["medicao"] = "ligada"
    url = f"{base}/ISAPI/Thermal/channels/{int(canal)}/thermometry/pixelToPixelParam"
    atual = requests.get(url, auth=auth, timeout=10, verify=False)
    if atual.status_code == 200 and "<visiblePicEnabled>true</visiblePicEnabled>" in atual.text:
        r = _put_xml(url, usuario, senha, atual.text.replace("<visiblePicEnabled>true</visiblePicEnabled>", "<visiblePicEnabled>false</visiblePicEnabled>", 1))
        feito["foto_colorida"] = "desligada" if r.status_code == 200 else f"recusado HTTP {r.status_code}"
    return feito


def buscar_foto(base: str, usuario: str, senha: str, canal_video: int = 1, timeout: float = 15.0) -> bytes:
    """Foto (JPEG) do canal de video -- 1 = colorido, 2 = termico. So na hora
    do alerta: a leitura de 2 em 2 s vem sem a colorida para poupar o link."""
    url = f"{base}/ISAPI/Streaming/channels/{int(canal_video)}01/picture"
    r = None
    for auth in (HTTPDigestAuth(usuario, senha), HTTPBasicAuth(usuario, senha)):
        r = requests.get(url, auth=auth, timeout=timeout, verify=False)
        if r.status_code not in (401, 403):
            break
    if r is None or r.status_code != 200 or not r.content.startswith(b"\xff\xd8"):
        raise ValueError(f"foto do canal {canal_video} nao veio (HTTP {getattr(r, 'status_code', '?')})")
    return r.content


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
