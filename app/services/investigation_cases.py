"""Casos da Investigacao: os trechos de gravacao que interessam a uma ocorrencia.

Um caso junta momentos de cameras diferentes ("02:08 Patio", "02:13 Oficina"),
com anotacao, para virar prova. Fica num JSON por tenant -- nunca compartilhado
entre clientes (tenant_scoped_path) -- porque o volume e pequeno (dezenas de
casos, poucos itens cada) e precisa sobreviver a recreate (volume /app/data).

So guarda referencias (gravador, canal, horario). Credencial nunca entra aqui.
"""
from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.tenant_context import tenant_scoped_path

_LOCK = threading.Lock()
_ARQ = "investigacao_casos.json"
_MAX_ITENS = 200


def _ler() -> List[Dict[str, Any]]:
    p = tenant_scoped_path(_ARQ)
    if not p.exists():
        return []
    try:
        dados = json.loads(p.read_text(encoding="utf-8") or "[]")
        return dados if isinstance(dados, list) else []
    except Exception:
        return []


def _gravar(casos: List[Dict[str, Any]]) -> None:
    p = tenant_scoped_path(_ARQ)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(casos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def listar() -> List[Dict[str, Any]]:
    with _LOCK:
        casos = _ler()
    return sorted(casos, key=lambda c: c.get("criado_em") or "", reverse=True)


def _achar(casos: List[Dict[str, Any]], caso_id: str) -> Dict[str, Any]:
    for c in casos:
        if c.get("id") == caso_id:
            return c
    raise KeyError("caso nao encontrado")


def criar(titulo: str, site: str = "", autor: str = "") -> Dict[str, Any]:
    titulo = str(titulo or "").strip()[:120]
    if not titulo:
        raise ValueError("de um titulo ao caso")
    with _LOCK:
        casos = _ler()
        numero = max([int(c.get("numero") or 0) for c in casos] + [0]) + 1
        caso = {"id": secrets.token_hex(6), "numero": numero, "titulo": titulo, "site": str(site or "")[:80],
                "autor": str(autor or "")[:80], "criado_em": _agora(), "notas": "", "itens": []}
        casos.append(caso)
        _gravar(casos)
    return caso


def adicionar_item(caso_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
    limpo = {
        "id": secrets.token_hex(5),
        "host": str(item.get("host") or "").strip()[:64],
        "http_port": int(item.get("http_port") or 80),
        "canal": int(item.get("canal") or 0),
        "camera": str(item.get("camera") or "")[:120],
        "momento": str(item.get("momento") or "")[:19],
        "inicio": str(item.get("inicio") or "")[:19],
        "fim": str(item.get("fim") or "")[:19],
        "nota": str(item.get("nota") or "")[:500],
        "adicionado_em": _agora(),
    }
    if not limpo["host"] or limpo["canal"] <= 0 or not limpo["momento"]:
        raise ValueError("item sem gravador, canal ou horario")
    with _LOCK:
        casos = _ler()
        caso = _achar(casos, caso_id)
        if len(caso["itens"]) >= _MAX_ITENS:
            raise ValueError("caso cheio")
        caso["itens"].append(limpo)
        caso["itens"].sort(key=lambda i: i.get("momento") or "")
        _gravar(casos)
    return caso


def remover_item(caso_id: str, item_id: str) -> Dict[str, Any]:
    with _LOCK:
        casos = _ler()
        caso = _achar(casos, caso_id)
        caso["itens"] = [i for i in caso["itens"] if i.get("id") != item_id]
        _gravar(casos)
    return caso


def atualizar(caso_id: str, notas: Optional[str] = None, item_id: str = "", nota_item: Optional[str] = None
              ) -> Dict[str, Any]:
    with _LOCK:
        casos = _ler()
        caso = _achar(casos, caso_id)
        if notas is not None:
            caso["notas"] = str(notas)[:5000]
        if item_id and nota_item is not None:
            for i in caso["itens"]:
                if i.get("id") == item_id:
                    i["nota"] = str(nota_item)[:500]
        _gravar(casos)
    return caso
