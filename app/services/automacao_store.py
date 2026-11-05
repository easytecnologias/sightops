"""Automacoes: regra "quando a camera termica detectar, faca isso".

Toda regra nasce em modo 'simular': registra o que faria e nao toca no
equipamento. Equipamento do cliente e vivo, entao passar para 'valer' e uma
decisao explicita (rota so de admin).

O alvo de cada acao tem de estar no inventario do proprio cliente: nunca um IP
digitado. Toda consulta filtra pelo cliente da sessao.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.tenant_context import get_current_tenant_slug
from app.services import db_store

ID_RE = re.compile(r"^[0-9a-f]{32}$")
MODOS = ("simular", "valer")
TIPOS = ("saida", "speed_preset")
MAX_ACOES = 8
MAX_SEGUNDOS = 600


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tenant() -> str:
    slug = get_current_tenant_slug()
    if not slug:
        raise PermissionError("Cliente não identificado.")
    return slug


def _txt(v: Any) -> str:
    return str(v or "").strip()


def _site_ok(site: Any) -> bool:
    from app.services.termico_store import _site_ok as ok
    return ok(site)


def equipamento_do_inventario(ip: str, connector_id: str = "") -> Optional[Dict[str, Any]]:
    """Linha do inventario do cliente da sessao com esse IP + conector."""
    from app.services.inventory_json import load_inventory_json

    for modo in ("switch", "olt"):
        try:
            linhas = load_inventory_json(mode=modo)
        except Exception:
            linhas = []
        for row in linhas or []:
            if _txt(row.get("ip")) == _txt(ip) and _txt(row.get("remote_connector_id")) == _txt(connector_id):
                return {
                    "ip": _txt(ip), "connector_id": _txt(connector_id), "mac": _txt(row.get("mac")).lower(),
                    "site": _txt(row.get("site") or row.get("local")), "porta": int(row.get("http_port") or 80),
                    "nome": _txt(row.get("titulo") or row.get("title")) or _txt(ip),
                    "modelo": _txt(row.get("modelo") or row.get("model")),
                }
    return None


def _validar_acoes(acoes: Any) -> List[Dict[str, Any]]:
    if not isinstance(acoes, list) or not acoes:
        raise ValueError("Informe pelo menos uma ação.")
    if len(acoes) > MAX_ACOES:
        raise ValueError(f"No máximo {MAX_ACOES} ações por automação.")
    saida: List[Dict[str, Any]] = []
    for a in acoes:
        if not isinstance(a, dict) or a.get("tipo") not in TIPOS:
            raise ValueError("Tipo de ação inválido.")
        eq = equipamento_do_inventario(_txt(a.get("ip")), _txt(a.get("connector_id")))
        if not eq or not _site_ok(eq["site"]):
            raise ValueError(f"O equipamento {_txt(a.get('ip'))} não está no inventário deste cliente.")
        item: Dict[str, Any] = {"tipo": a["tipo"], "ip": eq["ip"], "connector_id": eq["connector_id"], "nome": eq["nome"]}
        try:
            if a["tipo"] == "saida":
                item["saida"] = int(a.get("saida") or 1)
                item["segundos"] = int(a.get("segundos") or 30)
                if not 1 <= item["saida"] <= 16:
                    raise ValueError
                if not 1 <= item["segundos"] <= MAX_SEGUNDOS:
                    raise ValueError
            else:
                item["preset"] = int(a.get("preset") or 0)
                if not 1 <= item["preset"] <= 300:
                    raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"Ação em {eq['nome']}: número fora da faixa (saída 1 a 16, tempo 1 a {MAX_SEGUNDOS} s, preset 1 a 300).")
        saida.append(item)
    return saida


def _publica(r: Dict[str, Any]) -> Dict[str, Any]:
    try:
        acoes = json.loads(r.get("acoes") or "[]")
    except Exception:
        acoes = []
    return {"id": r["id"], "nome": r.get("nome") or "", "ativo": bool(int(r.get("ativo") or 0)),
            "modo": r.get("modo") or "simular", "origem_camera_id": r.get("origem_camera_id") or "",
            "intervalo_s": int(r.get("intervalo_s") or 120), "acoes": acoes}


def _regra(c: Any, tenant: str, regra_id: str) -> Dict[str, Any]:
    if not ID_RE.match(regra_id or ""):
        raise LookupError("Automação não encontrada.")
    r = c.execute("SELECT * FROM automacoes WHERE tenant_slug=? AND id=?", (tenant, regra_id)).fetchone()
    if not r:
        raise LookupError("Automação não encontrada.")
    return dict(r)


def listar() -> Dict[str, Any]:
    tenant = _tenant()
    with db_store._conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM automacoes WHERE tenant_slug=?", (tenant,)).fetchall()]
        hist = [dict(r) for r in c.execute(
            "SELECT automacao_id, alerta_id, modo, acao, ok, resposta, criado_at FROM automacao_execucoes "
            "WHERE tenant_slug=? ORDER BY criado_at DESC LIMIT 100", (tenant,)).fetchall()]
    rows.sort(key=lambda r: (r.get("nome") or "").lower())
    return {"automacoes": [_publica(r) for r in rows], "execucoes": hist}


def salvar(dados: Dict[str, Any], regra_id: str = "") -> Dict[str, Any]:
    tenant = _tenant()
    nome = _txt(dados.get("nome"))[:120]
    if not nome:
        raise ValueError("Dê um nome à automação.")
    acoes = _validar_acoes(dados.get("acoes"))
    modo = _txt(dados.get("modo")) or "simular"
    if modo not in MODOS:
        raise ValueError("Modo inválido.")
    try:
        intervalo = int(dados.get("intervalo_s") if dados.get("intervalo_s") is not None else 120)
    except (TypeError, ValueError):
        raise ValueError("Intervalo inválido.")
    if not 10 <= intervalo <= 3600:
        raise ValueError("Intervalo: use de 10 a 3600 segundos.")
    origem = _txt(dados.get("origem_camera_id"))
    agora = _agora()
    ativo = 1 if dados.get("ativo", True) else 0
    with db_store._conn() as c:
        if origem and not c.execute("SELECT id FROM termico_cameras WHERE tenant_slug=? AND id=?", (tenant, origem)).fetchone():
            raise ValueError("Câmera de origem não encontrada.")
        valores = (nome, ativo, modo, origem, intervalo, json.dumps(acoes, ensure_ascii=False), agora)
        if regra_id:
            _regra(c, tenant, regra_id)
            c.execute("UPDATE automacoes SET nome=?, ativo=?, modo=?, origem_camera_id=?, intervalo_s=?, acoes=?, updated_at=? "
                      "WHERE tenant_slug=? AND id=?", valores + (tenant, regra_id))
        else:
            regra_id = uuid.uuid4().hex
            c.execute("INSERT INTO automacoes(nome, ativo, modo, origem_camera_id, intervalo_s, acoes, updated_at, id, tenant_slug, created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)", valores + (regra_id, tenant, agora))
        return _publica(_regra(c, tenant, regra_id))


def excluir(regra_id: str) -> Dict[str, Any]:
    tenant = _tenant()
    with db_store._conn() as c:
        _regra(c, tenant, regra_id)
        c.execute("DELETE FROM automacoes WHERE tenant_slug=? AND id=?", (tenant, regra_id))
    return {"ok": True}


def regras_da_camera(camera_id: str) -> List[Dict[str, Any]]:
    tenant = _tenant()
    with db_store._conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM automacoes WHERE tenant_slug=? AND ativo=1 AND (origem_camera_id='' OR origem_camera_id=?)",
            (tenant, camera_id)).fetchall()]
    return [_publica(r) for r in rows]


def obter(regra_id: str) -> Dict[str, Any]:
    tenant = _tenant()
    with db_store._conn() as c:
        return _publica(_regra(c, tenant, regra_id))


def ultima_execucao(regra_id: str) -> str:
    tenant = _tenant()
    with db_store._conn() as c:
        r = c.execute("SELECT MAX(criado_at) AS m FROM automacao_execucoes WHERE tenant_slug=? AND automacao_id=?",
                      (tenant, regra_id)).fetchone()
    return _txt(dict(r).get("m")) if r else ""


def registrar_execucao(regra_id: str, alerta_id: str, modo: str, acao: Dict[str, Any], ok: bool, resposta: str) -> None:
    tenant = _tenant()
    with db_store._conn() as c:
        c.execute("INSERT INTO automacao_execucoes(id, tenant_slug, automacao_id, alerta_id, modo, acao, ok, resposta, criado_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?)",
                  (uuid.uuid4().hex, tenant, regra_id, alerta_id, modo, json.dumps(acao, ensure_ascii=False),
                   1 if ok else 0, _txt(resposta)[:300], _agora()))
