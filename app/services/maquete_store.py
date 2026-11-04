"""Maquete 3D -- projetos por cliente (planta enviada + o que foi montado nela).

Cada projeto guarda o PDF e as texturas em data/tenants/<slug>/maquete/<id>/ e
duas colunas JSON: `leitura` (paredes achadas no PDF, so o servidor escreve) e
`layout` (cameras, eletrocalha, caixas e rack que o cliente montou).

A leitura do PDF leva ~15 s: roda numa thread e o projeto fica "processando"
ate terminar ("pronto" ou "erro" com o motivo). Toda consulta filtra pelo
tenant -- o id sozinho nunca basta.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.tenant_context import get_current_tenant_slug, tenant_scoped_path
from app.services import db_store

log = logging.getLogger(__name__)

MAX_PDF = 60 * 1024 * 1024
MAX_LAYOUT = 2 * 1024 * 1024
TEXTURA_RE = re.compile(r"^piso_\d{1,2}\.jpg$")
ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tenant() -> str:
    # sem cliente na sessao, recusa (nao cai no "default" do db_store)
    slug = get_current_tenant_slug()
    if not slug:
        raise PermissionError("Cliente não identificado.")
    return slug


def _pasta(tenant: str, projeto_id: str) -> Path:
    if not ID_RE.match(projeto_id or ""):
        raise LookupError("Projeto não encontrado.")
    return tenant_scoped_path(f"maquete/{projeto_id}", tenant)


def _row(c: Any, sql: str, params: tuple) -> Optional[Dict[str, Any]]:
    r = c.execute(sql, params).fetchone()
    return dict(r) if r else None


def _json(raw: Any, padrao: Any) -> Any:
    try:
        return json.loads(raw) if raw else padrao
    except Exception:
        return padrao


def _resumo(r: Dict[str, Any]) -> Dict[str, Any]:
    leitura = _json(r.get("leitura"), {})
    layout = _json(r.get("layout"), {})
    return {
        "id": r["id"], "nome": r.get("nome") or "", "arquivo": r.get("arquivo") or "",
        "status": r.get("status") or "", "erro": r.get("erro") or "",
        "escala": leitura.get("escala") or "",
        "pisos": [p.get("nome") for p in leitura.get("pisos") or []],
        "cameras": len(layout.get("cams") or []),
        "criado_por": r.get("criado_por") or "",
        "created_at": r.get("created_at") or "", "updated_at": r.get("updated_at") or "",
    }


# --------------------------------------------------------------------------- leitura

def listar() -> Dict[str, Any]:
    tenant = _tenant()
    with db_store._conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM maquete_projetos WHERE tenant_slug=? ORDER BY updated_at DESC", (tenant,)).fetchall()]
    return {"ok": True, "projetos": [_resumo(r) for r in rows]}


def obter(projeto_id: str) -> Dict[str, Any]:
    tenant = _tenant()
    with db_store._conn() as c:
        r = _row(c, "SELECT * FROM maquete_projetos WHERE tenant_slug=? AND id=?", (tenant, projeto_id))
    if not r:
        raise LookupError("Projeto não encontrado.")
    out = _resumo(r)
    out["leitura"] = _json(r.get("leitura"), {})
    out["layout"] = _json(r.get("layout"), {})
    return {"ok": True, "projeto": out}


def textura(projeto_id: str, arquivo: str) -> Path:
    tenant = _tenant()
    if not TEXTURA_RE.match(arquivo or ""):
        raise LookupError("Arquivo não encontrado.")
    with db_store._conn() as c:
        if not _row(c, "SELECT id FROM maquete_projetos WHERE tenant_slug=? AND id=?", (tenant, projeto_id)):
            raise LookupError("Projeto não encontrado.")
    arq = _pasta(tenant, projeto_id) / arquivo
    if not arq.is_file():
        raise LookupError("Arquivo não encontrado.")
    return arq


# --------------------------------------------------------------------------- gravacao

def criar(nome: str, arquivo: str, pdf: bytes, usuario: str = "") -> Dict[str, Any]:
    tenant = _tenant()
    if not pdf:
        raise ValueError("Arquivo vazio.")
    if len(pdf) > MAX_PDF:
        raise ValueError("PDF maior que 60 MB.")
    if not pdf[:1024].lstrip().startswith(b"%PDF"):
        raise ValueError("Envie a planta em PDF (exportado do CAD). DWG e foto ainda não são aceitos.")
    nome = (nome or "").strip()[:120] or re.sub(r"\.pdf$", "", (arquivo or "Planta").strip(), flags=re.I)[:120]
    novo = uuid.uuid4().hex
    pasta = _pasta(tenant, novo)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "planta.pdf").write_bytes(pdf)
    now = _now()
    with db_store._conn() as c:
        c.execute(
            "INSERT INTO maquete_projetos(id, tenant_slug, nome, arquivo, status, erro, leitura, layout, criado_por, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, 'processando', '', '', '', ?, ?, ?)",
            (novo, tenant, nome, (arquivo or "")[:200], (usuario or "")[:120], now, now),
        )
    threading.Thread(target=_processar, args=(tenant, novo), name=f"maquete-{novo[:8]}", daemon=True).start()
    return {"ok": True, "id": novo, "status": "processando"}


def _processar(tenant: str, projeto_id: str) -> None:
    from app.services.maquete_planta import PlantaInvalida, ler_planta
    pasta = _pasta(tenant, projeto_id)
    status, erro, leitura = "erro", "", ""
    try:
        res = ler_planta((pasta / "planta.pdf").read_bytes(), pasta)
        leitura, status = json.dumps(res, ensure_ascii=False), "pronto"
    except PlantaInvalida as exc:
        erro = str(exc)
    except Exception as exc:  # nunca deixa o projeto preso em "processando"
        log.exception("maquete: falha lendo planta %s/%s", tenant, projeto_id)
        erro = f"Falha ao ler a planta ({type(exc).__name__})."
    try:
        with db_store._conn() as c:
            c.execute(
                "UPDATE maquete_projetos SET status=?, erro=?, leitura=?, updated_at=? WHERE tenant_slug=? AND id=?",
                (status, erro[:500], leitura, _now(), tenant, projeto_id),
            )
    except Exception:
        log.exception("maquete: falha gravando leitura %s/%s", tenant, projeto_id)


def salvar(projeto_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    sets, vals = [], []
    if "nome" in payload:
        nome = str(payload.get("nome") or "").strip()[:120]
        if not nome:
            raise ValueError("Informe o nome do projeto.")
        sets.append("nome=?"); vals.append(nome)
    if "layout" in payload:
        layout = payload.get("layout")
        if not isinstance(layout, dict):
            raise ValueError("Layout inválido.")
        txt = json.dumps(layout, ensure_ascii=False)
        if len(txt) > MAX_LAYOUT:
            raise ValueError("Projeto grande demais para salvar.")
        sets.append("layout=?"); vals.append(txt)
    if not sets:
        raise ValueError("Nada para salvar.")
    now = _now()
    with db_store._conn() as c:
        if not _row(c, "SELECT id FROM maquete_projetos WHERE tenant_slug=? AND id=?", (tenant, projeto_id)):
            raise LookupError("Projeto não encontrado.")
        c.execute(f"UPDATE maquete_projetos SET {', '.join(sets)}, updated_at=? WHERE tenant_slug=? AND id=?",
                  (*vals, now, tenant, projeto_id))
    return {"ok": True, "updated_at": now}


def excluir(projeto_id: str) -> Dict[str, Any]:
    tenant = _tenant()
    with db_store._conn() as c:
        if not _row(c, "SELECT id FROM maquete_projetos WHERE tenant_slug=? AND id=?", (tenant, projeto_id)):
            raise LookupError("Projeto não encontrado.")
        c.execute("DELETE FROM maquete_projetos WHERE tenant_slug=? AND id=?", (tenant, projeto_id))
    shutil.rmtree(_pasta(tenant, projeto_id), ignore_errors=True)
    return {"ok": True}
