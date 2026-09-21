"""Log de acoes de ONU (autorizar, aplicar servico/VLAN, excluir, consultar
sinal/MACs) -- historico real de "o que foi feito", nao o estado atual do
inventario (que e o que `/api/olt/rows` ja mostra).

Pedido explicito do usuario: a tela de Implantacao > ONU so mostrava o
inventario mais recente, entao uma exclusao simplesmente sumia da lista sem
deixar rastro -- ele queria "a onu gpon 7 onu 2 foi excluida", "foi
adicionada", "foi consultada", tipo log de OLT.

Falha ao gravar o log NUNCA deve derrubar a acao real na OLT -- por isso
`log_onu_action` engole qualquer excecao (so registra um aviso).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.db_store import _conn, _current_tenant_slug

logger = logging.getLogger("cam-snapshot")

ACTION_LABELS = {
    "add_onu": "autorizada",
    "add_onu_bridge": "servico/VLAN reaplicado",
    "delete_onu": "excluida",
    "onu_signal": "consultada",
}


def log_onu_action(
    action: str,
    *,
    olt_id: Optional[int] = None,
    olt_ip: str = "",
    olt_name: str = "",
    site: str = "",
    pon: Any = "",
    onu: Any = "",
    serial: str = "",
    vlan: str = "",
    ok: bool = True,
    detail: str = "",
) -> None:
    try:
        tenant = _current_tenant_slug()
        with _conn() as c:
            c.execute(
                "INSERT INTO onu_action_log"
                "(tenant_slug, olt_id, olt_ip, olt_name, site, pon, onu, serial, vlan, action, ok, detail) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tenant,
                    int(olt_id) if olt_id else None,
                    str(olt_ip or ""),
                    str(olt_name or ""),
                    str(site or ""),
                    str(pon or ""),
                    str(onu or ""),
                    str(serial or ""),
                    str(vlan or ""),
                    action,
                    1 if ok else 0,
                    str(detail or "")[:500],
                ),
            )
    except Exception:
        logger.warning("Falha ao gravar log de acao de ONU (acao=%s)", action, exc_info=True)


def list_onu_actions(olt_ip: str = "", limit: int = 30) -> List[Dict[str, Any]]:
    tenant = _current_tenant_slug()
    limit = max(1, min(int(limit or 30), 200))
    with _conn() as c:
        if olt_ip:
            rows = c.execute(
                "SELECT * FROM onu_action_log WHERE tenant_slug = ? AND olt_ip = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (tenant, str(olt_ip), limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM onu_action_log WHERE tenant_slug = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (tenant, limit),
            ).fetchall()
    return [dict(r) for r in rows or []]
