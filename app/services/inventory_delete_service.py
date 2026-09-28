from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from app.core.paths import ensure_dirs
from app.models.requests import InventoryDeleteRequest
from app.services.inventory_json import inventory_row_key, load_inventory_json, save_inventory_json
from app.services.photo_store import ip_to_stem, snapshot_storage_dir

# Todos os modos de inventario, nao apenas os que esta exclusao processou: a
# MESMA camera pode ter linha em "basic" e em "olt", e apagar em um modo nao
# pode levar a foto que o outro ainda usa.
logger = logging.getLogger("cam-snapshot")

_ALL_MODES = ("basic", "olt", "switch")


def _row_snapshot_names(row: Dict[str, Any]) -> set[str]:
    """Nomes de arquivo de snapshot que esta linha pode estar usando."""
    names: set[str] = set()
    for key in ("snapshot_path", "snapshot_file", "snapshot_url", "thumb_url"):
        raw = str(row.get(key) or "").strip()
        if raw and not raw.lower().startswith(("http://", "https://")):
            name = Path(raw).name
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                names.add(name)
    ip = str(row.get("ip") or row.get("IP") or "").strip()
    if ip:
        stem = ip_to_stem(ip)
        names.add(f"{stem}.jpg")
        # Nome por CONECTOR+IP: dois clientes com o mesmo IP privado nao podem
        # dividir o mesmo arquivo, entao a captura prefixa com o conector.
        conn = str(row.get("remote_connector_id") or row.get("connector_id") or "").strip()
        if conn:
            conn_stem = "".join(c if (c.isalnum() or c == "_") else "_" for c in conn)
            names.add(f"{conn_stem}__{stem}.jpg")
    return names


def _delete_orphan_snapshots(removed_rows: List[Dict[str, Any]]) -> List[str]:
    """Apaga o JPG das linhas removidas que nenhuma linha viva mais referencia.

    Sem isto o arquivo ficava para sempre no disco e voltava a ser exibido: o
    nome carrega o IP, entao a proxima camera que herdasse aquele IP herdava
    junto a foto da anterior. Foi o que o usuario viu -- apagou o inventario
    inteiro, refez a varredura, e a foto antiga voltou numa camera offline.
    """
    if not removed_rows:
        return []

    alvos: set[str] = set()
    for row in removed_rows:
        if isinstance(row, dict):
            alvos |= _row_snapshot_names(row)
    if not alvos:
        return []

    em_uso: set[str] = set()
    for mode in _ALL_MODES:
        try:
            for row in load_inventory_json(mode=mode) or []:
                if isinstance(row, dict):
                    em_uso |= _row_snapshot_names(row)
        except Exception:
            # Inventario ilegivel nao pode virar autorizacao para apagar foto.
            return []

    apagados: List[str] = []
    try:
        base = snapshot_storage_dir()
    except Exception:
        return []
    for name in sorted(alvos - em_uso):
        alvo = base / Path(name).name
        try:
            if alvo.exists() and alvo.is_file():
                alvo.unlink()
                apagados.append(alvo.name)
        except Exception:
            continue
    return apagados


def _remover_hosts_do_zabbix(removed_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apaga no Zabbix o host das cameras que acabaram de sair do inventario.

    Sem isto o host ficava para sempre: a camera sumia da tela e continuava
    sendo pingada, alarmando por um equipamento que ninguem tem mais. Era a
    origem dos 165 hosts orfaos encontrados no rads em 2026-09-28.

    Falha aqui NAO derruba a exclusao do inventario -- apagar a camera e o que
    o usuario pediu; o Zabbix e consequencia. O erro volta no retorno para
    aparecer na tela em vez de morrer em silencio.
    """
    ips = sorted({
        str((row or {}).get("ip") or (row or {}).get("IP") or "").strip()
        for row in removed_rows if isinstance(row, dict)
    } - {""})
    if not ips:
        return {"ok": True, "removed": 0}
    try:
        from app.api.endpoints.maintenance import (
            _load_settings,
            _normalize_zabbix_url,
            _zabbix_api_call,
            _zabbix_effective_sync_config,
            _zabbix_host_belongs_to_tenant,
            _zabbix_login,
            _zabbix_tenant_slug,
        )
    except Exception as exc:
        return {"ok": False, "error": f"zabbix indisponivel: {exc}"}
    try:
        cfg = _zabbix_effective_sync_config((_load_settings() or {}).get("zabbix_ip_sync") or {})
        url = _normalize_zabbix_url(cfg.get("url"))
        if not url:
            return {"ok": True, "removed": 0, "detail": "zabbix nao configurado"}
        auth = _zabbix_login(url, cfg.get("user"), cfg.get("pass") or cfg.get("password"))
        if not auth:
            return {"ok": False, "error": "login no zabbix falhou"}
        tenant = _zabbix_tenant_slug()
        # Casa pelo IP da INTERFACE: o nome do host carrega o IP real, mas em
        # conector isolado a interface aponta para o IP virtual -- procurar so
        # pelo nome deixaria o host de tras.
        achados = _zabbix_api_call(
            url, "host.get",
            {"output": ["hostid", "host", "name"], "selectInterfaces": ["ip"]},
            auth,
        ) or []
        alvo = []
        for h in achados:
            if not _zabbix_host_belongs_to_tenant(h, tenant):
                continue  # host de OUTRO cliente com o mesmo IP privado
            nome = str(h.get("host") or "")
            ifaces = {str(i.get("ip") or "") for i in (h.get("interfaces") or [])}
            if any(ip in nome for ip in ips) or (ifaces & set(ips)):
                alvo.append(str(h.get("hostid")))
        if not alvo:
            return {"ok": True, "removed": 0}
        _zabbix_api_call(url, "host.delete", alvo, auth)
        logger.warning("inventario: %s host(s) removidos do Zabbix junto com as cameras", len(alvo))
        return {"ok": True, "removed": len(alvo)}
    except Exception as exc:
        logger.exception("falha ao remover hosts do Zabbix na exclusao de camera")
        return {"ok": False, "error": str(exc)}


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


    snapshots_removed = _delete_orphan_snapshots(removed_rows)
    zabbix_removed = _remover_hosts_do_zabbix(removed_rows)

    inventory = inventories.get("olt") or inventories.get(modes[0], [])
    return {
        "ok": True,
        "removed": len(removed_ips),
        "ips_removed": sorted(list(removed_ips)),
        "keys_removed": sorted(list(removed_keys)),
        "snapshots_removed": snapshots_removed,
        "zabbix": zabbix_removed,
        "inventory": inventory,
        "inventories": inventories,
    }
