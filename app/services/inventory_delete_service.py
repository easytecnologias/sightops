from __future__ import annotations

from typing import Any, Dict, List

from app.core.paths import ensure_dirs
from app.models.requests import InventoryDeleteRequest
from app.services.inventory_json import inventory_row_key, load_inventory_json, save_inventory_json


def inventory_delete(req: InventoryDeleteRequest) -> Dict[str, Any]:
    ensure_dirs()
    ips_set = {ip.strip() for ip in (req.ips or []) if ip and ip.strip()}
    keys_set = {str(key or "").strip() for key in (getattr(req, "keys", []) or []) if str(key or "").strip()}
    connector_id = str(getattr(req, "connector_id", "") or "").strip()
    site = str(getattr(req, "site", "") or "").strip()
    if not ips_set and not keys_set:
        return {"ok": False, "error": "Nenhum IP ou chave recebido para apagar."}

    def get_row_ip(row: Dict[str, Any]) -> str:
        if "ip" in row:
            return str(row["ip"]).strip()
        if "IP" in row:
            return str(row["IP"]).strip()
        return ""

    removed_ips: set[str] = set()
    removed_keys: set[str] = set()
    removed_rows: List[Dict[str, Any]] = []
    inventories: Dict[str, List[Dict[str, Any]]] = {}
    raw_mode = str(getattr(req, "mode", "olt") or "olt").strip().lower()
    if raw_mode in {"all", "todos", "camera", "cameras"}:
        modes = ["basic", "olt", "switch"]
    elif raw_mode in {"basic", "basico", "básico", "base"}:
        modes = ["basic"]
    elif raw_mode in {"switch", "sw", "via_switch", "via-switch"}:
        modes = ["switch"]
    else:
        modes = ["olt"]

    for current_mode in modes:
        rows = load_inventory_json(mode=current_mode) or []
        rows_kept: List[Dict[str, Any]] = []
        for row in rows:
            rip = get_row_ip(row)
            row_key = inventory_row_key(row)
            row_connector = str(row.get("remote_connector_id") or row.get("connector_id") or "").strip()
            # A linha pode ter site, site_name e local DIFERENTES entre si
            # (ex.: site=BARRA DE SAO MIGUEL, site_name=TESTE, local=ESCOLA MEDEA).
            # A tela mostra e filtra por 'local'; casar so com 'site' fazia o
            # apagar nao encontrar nada e o usuario ficar horas sem conseguir.
            row_sites = {
                str(row.get(key) or "").strip().lower()
                for key in ("site", "site_name", "local", "LOCAL")
                if str(row.get(key) or "").strip()
            }
            row_site = str(row.get("site") or row.get("site_name") or row.get("local") or "").strip()
            scoped_match = True
            if connector_id:
                scoped_match = row_connector == connector_id
            elif site:
                scoped_match = site.strip().lower() in row_sites
            key_match = row_key in keys_set and scoped_match
            ip_match = bool(rip and rip in ips_set and scoped_match)
            should_remove = bool(key_match or ip_match)
            if should_remove:
                removed_ips.add(rip)
                removed_keys.add(row_key)
                removed_rows.append(row)
            else:
                rows_kept.append(row)
        save_inventory_json(rows_kept, mode=current_mode)
        inventories[current_mode] = rows_kept


    inventory = inventories.get("olt") or inventories.get(modes[0], [])
    return {
        "ok": True,
        "removed": len(removed_ips),
        "ips_removed": sorted(list(removed_ips)),
        "keys_removed": sorted(list(removed_keys)),
        "inventory": inventory,
        "inventories": inventories,
    }
