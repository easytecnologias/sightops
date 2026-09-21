from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from app.core.tenant_context import get_current_tenant_slug
from app.services.db_store import _conn

logger = logging.getLogger("cam-snapshot")


DEFAULT_PROFILES = (
    ("connector-default", "Conector MikroTik", "connector", 60, 2),
    ("olt-default", "OLT", "olt", 60, 2),
    ("onu-default", "ONU/ONT", "onu", 120, 2),
    ("camera-default", "Camera IP", "camera", 60, 2),
    ("nvr-default", "NVR", "nvr", 60, 2),
    ("dvr-default", "DVR", "dvr", 60, 2),
    ("windows-default", "Computador Windows", "windows", 120, 2),
    # underscore para casar com o fallback automatico de _observe_entity_on()
    # (f"{entity_type}-default", e entity_type="access_device"); o bloco de
    # access_device em refresh_from_inventory() nunca define profile_key, entao
    # so o underscore encontra a linha certa e pega o failure_threshold real.
    ("access_device-default", "Controladora de Acesso", "access_device", 180, 2),
    ("whatsapp-default", "Canal WhatsApp", "whatsapp", 300, 1),
)


def _tenant() -> str:
    return str(get_current_tenant_slug() or "default").strip().lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    match = re.search(r"-?\d+(?:[.,]\d+)?", _text(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def normalize_status(value: Any) -> str:
    status = _text(value).lower()
    if status in {"online", "up", "ok", "active", "ativo", "login ok"}:
        return "up"
    if status in {"offline", "down", "los", "inactive", "inativo", "error", "erro", "auth_failed", "timeout"}:
        return "down"
    if status in {"maintenance", "manutencao", "em manutencao"}:
        return "maintenance"
    if status in {"unstable", "flapping", "instavel", "oscilando"}:
        return "unstable"
    return "unknown"


def ensure_default_profiles() -> None:
    tenant = _tenant()
    now = _now()
    with _conn() as c:
        for key, name, entity_type, interval, threshold in DEFAULT_PROFILES:
            c.execute(
                "INSERT INTO monitoring_profiles(tenant_slug,profile_key,name,entity_type,interval_seconds,failure_threshold,updated_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(tenant_slug,profile_key) DO NOTHING",
                (tenant, key, name, entity_type, interval, threshold, now),
            )


def _observe_entity_on(c: Any, item: Dict[str, Any], tenant: str) -> Dict[str, Any]:
    key = _text(item.get("entity_key"))
    entity_type = _text(item.get("entity_type")).lower()
    if not key or not entity_type:
        raise ValueError("entity_key e entity_type sao obrigatorios")
    raw_status = normalize_status(item.get("status"))
    now = _now()
    profile_key = _text(item.get("profile_key")) or f"{entity_type}-default"
    detail = json.dumps(item.get("detail") or {}, ensure_ascii=False)
    current_row = c.execute(
            "SELECT * FROM monitoring_entities WHERE tenant_slug=? AND entity_key=?", (tenant, key)
        ).fetchone()
    current = dict(current_row or {})
    old = _text(current.get("status")) or "unknown"
    failures = int(current.get("consecutive_failures") or 0)
    threshold_row = c.execute(
            "SELECT failure_threshold FROM monitoring_profiles WHERE tenant_slug=? AND profile_key=?",
            (tenant, profile_key),
        ).fetchone()
    threshold = int(dict(threshold_row or {}).get("failure_threshold") or 2)
    if raw_status == "down":
        failures += 1
        status = "down" if failures >= threshold else "unstable"
    else:
        failures = 0
        status = raw_status
    changed_at = now if status != old else (current.get("last_changed_at") or now)
    values = (
            tenant, key, entity_type, _text(item.get("entity_id")), _text(item.get("parent_key")),
            _text(item.get("site")), _text(item.get("connector_id")), _text(item.get("display_name")) or key,
            profile_key, 1, status, old, failures, now, changed_at,
            _text(current.get("zabbix_hostid")), detail, now,
        )
    c.execute(
            "INSERT INTO monitoring_entities(tenant_slug,entity_key,entity_type,entity_id,parent_key,site,connector_id,display_name,profile_key,monitoring_enabled,status,previous_status,consecutive_failures,last_checked_at,last_changed_at,zabbix_hostid,detail_json,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_slug,entity_key) DO UPDATE SET "
            "entity_type=excluded.entity_type,entity_id=excluded.entity_id,parent_key=excluded.parent_key,site=excluded.site,connector_id=excluded.connector_id,display_name=excluded.display_name,profile_key=excluded.profile_key,monitoring_enabled=1,status=excluded.status,previous_status=excluded.previous_status,consecutive_failures=excluded.consecutive_failures,last_checked_at=excluded.last_checked_at,last_changed_at=excluded.last_changed_at,detail_json=excluded.detail_json,updated_at=excluded.updated_at",
            values,
        )
    if status != old:
        c.execute(
                "INSERT INTO monitoring_events(tenant_slug,entity_key,entity_type,from_status,to_status,message,detail_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (tenant, key, entity_type, old, status, f"{_text(item.get('display_name')) or key}: {old} -> {status}", detail, now),
            )
    return {"entity_key": key, "status": status, "previous_status": old, "failures": failures}


def observe_entity(item: Dict[str, Any]) -> Dict[str, Any]:
    ensure_default_profiles()
    tenant = _tenant()
    with _conn() as c:
        return _observe_entity_on(c, item, tenant)


def _observe_many(rows: Iterable[Dict[str, Any]], prune_entity_type: str = "") -> int:
    tenant = _tenant()
    items = list(rows)
    active_keys = {_text(row.get("entity_key")) for row in items if _text(row.get("entity_key"))}
    with _conn() as c:
        for row in items:
            _observe_entity_on(c, row, tenant)
        entity_type = _text(prune_entity_type).lower()
        if entity_type:
            existing = c.execute(
                "SELECT entity_key FROM monitoring_entities WHERE tenant_slug=? AND entity_type=? AND monitoring_enabled=1",
                (tenant, entity_type),
            ).fetchall()
            stale_keys = [
                _text(dict(row).get("entity_key")) for row in existing
                if _text(dict(row).get("entity_key")) not in active_keys
            ]
            for key in stale_keys:
                c.execute(
                    "UPDATE monitoring_entities SET monitoring_enabled=0,updated_at=? WHERE tenant_slug=? AND entity_key=?",
                    (_now(), tenant, key),
                )
    return len(items)


def refresh_from_inventory() -> Dict[str, Any]:
    from app.services.connector_service import list_connectors
    from app.services.inventory_json import load_inventory_json
    from app.services.olt_registry import list_olts
    from app.services.olt_service import list_macs
    from app.services.dashboard_service import _recorder_rows
    from app.services.windows_inventory_service import load_windows_inventory
    from app.services.access_control_store import list_devices as list_access_devices
    from app.services.access_control_notifications import list_access_whatsapp_channels

    ensure_default_profiles()
    counts: Dict[str, int] = {}
    connectors = list_connectors(False).get("connectors", [])
    counts["connector"] = _observe_many(({
        "entity_key": f"connector:{_text(r.get('id'))}", "entity_type": "connector", "entity_id": r.get("id"),
        "site": r.get("site"), "connector_id": r.get("id"), "display_name": r.get("name") or r.get("client"),
        "status": r.get("status"), "detail": {"last_seen": r.get("last_seen")},
    } for r in connectors if r.get("id")), prune_entity_type="connector")
    olts = list_olts(True)
    onus = list_macs().get("rows", [])
    olt_hosts_with_telemetry = {
        _text(row.get("olt_ip")) for row in onus
        if _text(row.get("olt_ip"))
        and _text(row.get("telemetry_updated_at"))
        and _text(row.get("oper_status") or row.get("status"))
    }

    def _olt_monitoring_status(row: Dict[str, Any]) -> str:
        if not row.get("active"):
            return "maintenance"
        if _text(row.get("host")) in olt_hosts_with_telemetry:
            return "up"
        tested = _text(row.get("last_test_status")).lower()
        if tested == "ok":
            return "up"
        if tested == "error":
            return "down"
        return "unknown"

    counts["olt"] = _observe_many(({
        "entity_key": f"olt:{r.get('id')}", "entity_type": "olt", "entity_id": r.get("id"), "site": r.get("site"),
        "connector_id": r.get("connector_id"), "parent_key": f"connector:{r.get('connector_id')}" if r.get("connector_id") else "",
        "display_name": r.get("name") or r.get("host"), "status": _olt_monitoring_status(r),
        "detail": {
            "host": r.get("host"), "vendor": r.get("vendor"), "model": r.get("model"),
            "last_test_status": _text(r.get("last_test_status")),
            "last_tested_at": _text(r.get("last_tested_at")),
            "last_test_detail": _text(r.get("last_test_detail")),
        },
    } for r in olts), prune_entity_type="olt")
    olt_by_host = {_text(r.get("host")): r for r in olts}
    counts["onu"] = _observe_many(({
        "entity_key": "onu:" + "|".join((_text(r.get("connector_id") or r.get("remote_connector_id")), _text(r.get("olt_ip")), _text(r.get("pon")), _text(r.get("onu_id") or r.get("onu") or r.get("onu_serial")))),
        "entity_type": "onu", "entity_id": r.get("onu_serial") or r.get("onu_id"), "site": r.get("site"),
        "connector_id": r.get("connector_id") or r.get("remote_connector_id"),
        "parent_key": f"olt:{olt_by_host.get(_text(r.get('olt_ip')), {}).get('id')}" if olt_by_host.get(_text(r.get("olt_ip"))) else "",
        "display_name": r.get("onu_name") or f"PON {r.get('pon')} / ONU {r.get('onu_id')}",
        "status": r.get("oper_status") or r.get("status"), "detail": {
            "onu_rx": r.get("onu_rx") or r.get("rx_onu") or r.get("onu_rx_power"),
            "olt_rx": r.get("olt_rx") or r.get("rx_olt"), "distance_km": r.get("distance_km"),
            "omci_status": r.get("omci_status"), "serial": r.get("onu_serial"), "pon": r.get("pon"),
        },
    } for r in onus), prune_entity_type="onu")
    signal_rows = []
    for row in onus:
        key = "onu:" + "|".join((_text(row.get("connector_id") or row.get("remote_connector_id")), _text(row.get("olt_ip")), _text(row.get("pon")), _text(row.get("onu_id") or row.get("onu") or row.get("onu_serial"))))
        onu_rx = _number(row.get("onu_rx") or row.get("rx_onu") or row.get("onu_rx_power"))
        olt_rx = _number(row.get("olt_rx") or row.get("rx_olt"))
        distance = _number(row.get("distance_km"))
        if onu_rx is None and olt_rx is None and distance is None:
            continue
        signal_rows.append((tenant := _tenant(), key, onu_rx, olt_rx, distance, _text(row.get("oper_status") or row.get("status")), _text(row.get("omci_status")), _now()))
    if signal_rows:
        with _conn() as c:
            for values in signal_rows:
                c.execute("INSERT INTO onu_signal_samples(tenant_slug,entity_key,onu_rx,olt_rx,distance_km,oper_status,omci_status,captured_at) VALUES(?,?,?,?,?,?,?,?)", values)
    counts["onu_signals"] = len(signal_rows)
    cameras = []
    for mode in ("basic", "olt", "switch"):
        cameras.extend((dict(r, _mode=mode) for r in (load_inventory_json(mode=mode) or [])))
    counts["camera"] = _observe_many(({
        "entity_key": f"camera:{r.get('_mode')}:{r.get('remote_connector_id') or r.get('connector_id') or 'local'}:{r.get('ip')}",
        "entity_type": "camera", "entity_id": r.get("inventory_key") or r.get("ip"), "site": r.get("local") or r.get("site"),
        "connector_id": r.get("remote_connector_id") or r.get("connector_id"), "display_name": r.get("titulo") or r.get("title") or r.get("ip"),
        "status": r.get("status"), "detail": {"ip": r.get("ip"), "mode": r.get("_mode"), "model": r.get("modelo") or r.get("model")},
    } for r in cameras if r.get("ip")), prune_entity_type="camera")
    for source in ("dvr", "nvr"):
        recorders = {}
        for r in _recorder_rows(source):
            host = _text(r.get("host") or r.get("ip"))
            if host: recorders.setdefault(host, r)
        counts[source] = _observe_many(({
            "entity_key": f"{source}:{r.get('remote_connector_id') or r.get('connector_id') or 'local'}:{host}",
            "entity_type": source, "entity_id": host, "site": r.get("local"), "connector_id": r.get("remote_connector_id") or r.get("connector_id"),
            "display_name": r.get("recorder_name") or r.get("nvr_name") or host, "status": r.get("status"), "detail": {"host": host, "model": r.get("recorder_model") or r.get("nvr_model")},
        } for host, r in recorders.items()), prune_entity_type=source)
    windows = load_windows_inventory()
    counts["windows"] = _observe_many(({
        "entity_key": f"windows:{r.get('connector_id') or 'local'}:{r.get('hostname') or r.get('ip')}", "entity_type": "windows",
        "entity_id": r.get("hostname") or r.get("ip"), "site": r.get("local") or r.get("site"), "connector_id": r.get("connector_id"),
        "display_name": r.get("hostname") or r.get("ip"), "status": r.get("status"), "detail": {"ip": r.get("ip")},
    } for r in windows if r.get("hostname") or r.get("ip")), prune_entity_type="windows")
    try:
        access_devices = list_access_devices()
        counts["access_device"] = _observe_many(({
            "entity_key": f"access_device:{r.get('id')}", "entity_type": "access_device", "entity_id": r.get("id"),
            "site": r.get("site"), "connector_id": r.get("connector_id"), "display_name": r.get("name") or r.get("host"),
            "status": r.get("status") if r.get("active") else "maintenance",
            "detail": {"host": r.get("host"), "vendor": r.get("vendor"), "model": r.get("model"), "last_seen_at": r.get("last_seen_at")},
        } for r in access_devices if r.get("id")), prune_entity_type="access_device")
    except Exception as exc:
        # refresh_from_inventory() roda por tenant dentro de um loop que
        # processa TODOS os tenants (app/main.py:_monitoring_refresh_loop).
        # Uma excecao aqui nao pode propagar: abortaria o refresh dos tenants
        # seguintes naquele ciclo, silenciosamente.
        logger.warning("Falha ao observar controladoras de acesso no monitoramento: %s", exc)
        counts["access_device"] = 0
    try:
        whatsapp_channels = list_access_whatsapp_channels()
        counts["whatsapp"] = _observe_many(({
            "entity_key": f"whatsapp:{c.get('site') or '__default__'}", "entity_type": "whatsapp",
            "entity_id": c.get("site") or "__default__", "site": c.get("site"), "display_name": c.get("label"),
            "status": "online" if c.get("connected") else "offline",
            "detail": {
                "phone_number_id": c.get("phone_number_id"), "display_phone_number": c.get("display_phone_number"),
                "quality_rating": c.get("quality_rating"),
            },
        } for c in whatsapp_channels), prune_entity_type="whatsapp")
    except Exception as exc:
        # list_access_whatsapp_channels() faz chamadas HTTP reais pra Meta
        # (timeout 15s cada) e decrypt() no token salvo -- ambos podem falhar
        # de verdade (Meta fora do ar, chave de cripto trocada) e nao podem
        # derrubar o refresh dos outros tenants no mesmo ciclo.
        logger.warning("Falha ao observar canais WhatsApp no monitoramento: %s", exc)
        counts["whatsapp"] = 0
    return {"ok": True, "tenant": _tenant(), "observed": counts, "total": sum(counts.values())}


def list_profiles() -> List[Dict[str, Any]]:
    ensure_default_profiles()
    with _conn() as c:
        rows = c.execute("SELECT * FROM monitoring_profiles WHERE tenant_slug=? ORDER BY entity_type,name", (_tenant(),)).fetchall()
    return [dict(r) for r in rows]


def list_entities(entity_type: str = "", status: str = "", limit: int = 500) -> List[Dict[str, Any]]:
    where, params = ["tenant_slug=?", "monitoring_enabled=1"], [_tenant()]
    if entity_type: where.append("entity_type=?"); params.append(entity_type)
    if status: where.append("status=?"); params.append(status)
    params.append(max(1, min(int(limit), 2000)))
    with _conn() as c:
        rows = c.execute(f"SELECT * FROM monitoring_entities WHERE {' AND '.join(where)} ORDER BY CASE status WHEN 'down' THEN 0 WHEN 'unstable' THEN 1 WHEN 'unknown' THEN 2 ELSE 3 END, display_name LIMIT ?", tuple(params)).fetchall()
    return [dict(r) for r in rows]


def monitoring_summary() -> Dict[str, Any]:
    ensure_default_profiles()
    with _conn() as c:
        rows = c.execute("SELECT entity_type,status,COUNT(1) AS count FROM monitoring_entities WHERE tenant_slug=? AND monitoring_enabled=1 GROUP BY entity_type,status", (_tenant(),)).fetchall()
        events = c.execute("SELECT * FROM monitoring_events WHERE tenant_slug=? ORDER BY created_at DESC LIMIT 20", (_tenant(),)).fetchall()
    by_type: Dict[str, Dict[str, int]] = {}
    for row in rows:
        item = dict(row); bucket = by_type.setdefault(item["entity_type"], {"total": 0, "up": 0, "down": 0, "unstable": 0, "unknown": 0, "maintenance": 0})
        status = item["status"] if item["status"] in bucket else "unknown"; bucket[status] += int(item["count"]); bucket["total"] += int(item["count"])
    return {"ok": True, "tenant": _tenant(), "types": by_type, "events": [dict(r) for r in events]}


def list_monitoring_tenants() -> List[str]:
    """Tenants com inventario no banco; nunca retorna dados das linhas."""
    found = {"default"}
    with _conn() as c:
        for table in ("sites", "ip_cameras", "recorders", "olts", "monitoring_profiles", "access_devices"):
            try:
                rows = c.execute(f"SELECT DISTINCT tenant_slug FROM {table}").fetchall()
                found.update(_text(dict(row).get("tenant_slug")).lower() for row in rows)
            except Exception:
                continue
    return sorted(value for value in found if value)


def list_onu_signal_history(entity_key: str, limit: int = 720) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT onu_rx,olt_rx,distance_km,oper_status,omci_status,captured_at FROM onu_signal_samples WHERE tenant_slug=? AND entity_key=? ORDER BY captured_at DESC LIMIT ?",
            (_tenant(), _text(entity_key), max(1, min(int(limit), 5000))),
        ).fetchall()
    return [dict(row) for row in rows]
