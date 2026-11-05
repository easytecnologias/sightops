"""E4: acento quebrado nao volta para a tela (index.html e js)."""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "frontend"

QUEBRADOS = re.compile(
    r"\b(?:NAo|possAvel|cAmeras?|v-deo|grava--es|informa--es|execu--o|Notifica--es|constru--o)\b"
    r"|Carregando-<|Aguardando (?:inicio|configuracao)-<"
)


def _sem_comentario_html(texto: str) -> str:
    return re.sub(r"<!--.*?-->", "", texto, flags=re.S)


def test_nada_quebrado_no_frontend():
    achados = []
    for arq in [RAIZ / "index.html", *sorted((RAIZ / "js").glob("*.js"))]:
        texto = arq.read_text(encoding="utf-8-sig")
        if arq.suffix == ".html":
            texto = _sem_comentario_html(texto)
        achados += [f"{arq.name}: {m.group(0)}" for m in QUEBRADOS.finditer(texto)]
    assert achados == []


def test_menu_com_acento():
    html = (RAIZ / "index.html").read_text(encoding="utf-8-sig")
    for rotulo in ("Implantação", "Inventário", "Integrações", "Manutenção", "Análise"):
        assert f'nav-section-label">{rotulo}<' in html
