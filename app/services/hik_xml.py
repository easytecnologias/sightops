"""Leitura de XML do ISAPI (Hikvision) em qualquer firmware.

O firmware antigo responde no namespace `http://www.hikvision.com/ver20/...`;
o novo (V5.x, ex.: DS-7732NXI-I4/S da Mega Alarmes, 14/10/2026) responde em
`http://www.isapi.org/ver20/...`. O codigo procurava as tags so no antigo:
o XML chegava inteiro e nada casava -- raio-x sem modelo nem canais ("confira
usuario e senha"), indice da Investigacao com zero trechos e, pior, erro de
escrita lido como sucesso. Todo leitor de resposta ISAPI passa por aqui.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

HIK_NS = "http://www.hikvision.com/ver20/XMLSchema"
NS = {"h": HIK_NS}
_OUTROS_NS = (
    "http://www.isapi.org/ver20/XMLSchema",
    "http://www.std-cgi.com/ver20/XMLSchema",
)


def normalizar(xml: str) -> str:
    """Troca os namespaces equivalentes pelo da Hikvision (o que `NS` usa)."""
    texto = xml or ""
    for outro in _OUTROS_NS:
        if outro in texto:
            texto = texto.replace(outro, HIK_NS)
    return texto


def ler(xml: str) -> Optional[ET.Element]:
    """Raiz do XML com o namespace normalizado, ou None se nao for XML."""
    try:
        return ET.fromstring(normalizar(xml))
    except Exception:
        return None
