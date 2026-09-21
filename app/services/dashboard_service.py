from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.core.database_runtime import database_runtime_status
from app.core.paths import (
    DATA_DIR,
    DVR_INVENTORY_JSON_PATH,
    DVR_SNAPSHOT_DIR,
    INVENTORY_JSON_PATH,
    KMZ_OUTPUT_DIR,
    NVR_INVENTORY_JSON_PATH,
    NVR_SNAPSHOT_DIR,
)
from app.core.settings import get_settings
from app.core.tenant_context import (
    get_current_tenant_slug,
    tenant_kmz_output_dir,
    tenant_recorder_inventory_path,
    tenant_scoped_path,
    tenant_snapshot_dir,
)
from app.services.db_store import legacy_rows_from_db
from app.services.inventory_json import inventory_row_key, load_inventory_json
from app.services.photo_store import resolve_snapshot_file
from app.services.windows_inventory_service import load_windows_inventory


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _is_online(row: Dict[str, Any]) -> bool:
    status = _lower(row.get("status") or row.get("health") or row.get("state"))
    return status in ("online", "ok", "up", "ativo", "active")


def _is_offline(row: Dict[str, Any]) -> bool:
    status = _lower(row.get("status") or row.get("health") or row.get("state"))
    return status in ("offline", "down", "inativo", "inactive", "auth_failed", "timeout", "erro", "error")


def _has_snapshot(row: Dict[str, Any], *, resolve_local: bool = False) -> bool:
    for key in (
        "snapshot_url",
        "snapshot_path",
        "snapshot_file",
        "thumb_url",
        "thumbnail_url",
        "imgbb_url",
        "imgbb_thumb_url",
        "display_url",
    ):
        if _text(row.get(key)):
            return True
    if resolve_local:
        snap_file = resolve_snapshot_file(
            path_hint=_text(row.get("snapshot_path") or row.get("snapshot_file")),
            ip=_text(row.get("ip") or row.get("host") or row.get("camera_ip") or row.get("ip_camera")),
        )
        if snap_file is not None:
            return True
    return False


def _has_local(row: Dict[str, Any]) -> bool:
    return bool(_text(row.get("local") or row.get("LOCAL") or row.get("site") or row.get("site_name")))


def _load_json_rows(path: Path) -> List[Dict[str, Any]]:
    try:
        if not path.exists():
            return []
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(obj, list):
        return [item for item in obj if isinstance(item, dict)]
    if isinstance(obj, dict):
        rows = obj.get("inventory") or obj.get("rows") or obj.get("data") or []
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


def _recorder_rows(source: str) -> List[Dict[str, Any]]:
    src = "nvr" if _lower(source) == "nvr" else "dvr"
    try:
        rows = legacy_rows_from_db(src)
        if rows:
            return rows
    except Exception:
        pass

    if get_current_tenant_slug():
        return _load_json_rows(tenant_recorder_inventory_path(src))
    return _load_json_rows(NVR_INVENTORY_JSON_PATH if src == "nvr" else DVR_INVENTORY_JSON_PATH)


def _status_counts(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    total = online = offline = unknown = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        total += 1
        if _is_online(row):
            online += 1
        elif _is_offline(row):
            offline += 1
        else:
            unknown += 1
    return {"total": total, "online": online, "offline": offline, "unknown": unknown}


def _missing_counts(rows: Iterable[Dict[str, Any]], *, resolve_local_snapshots: bool = False) -> Dict[str, int]:
    missing_snapshot = missing_local = missing_model = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if not _has_snapshot(row, resolve_local=resolve_local_snapshots):
            missing_snapshot += 1
        if not _has_local(row):
            missing_local += 1
        if not _text(row.get("modelo") or row.get("model") or row.get("camera_model") or row.get("recorder_model")):
            missing_model += 1
    return {
        "missing_snapshot": missing_snapshot,
        "missing_local": missing_local,
        "missing_model": missing_model,
    }


def _duplicate_count(rows: Iterable[Dict[str, Any]], keys: tuple[str, ...]) -> int:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        value = ""
        for key in keys:
            value = _lower(row.get(key))
            if value:
                break
        if not value:
            continue
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return len(duplicates)


def _snapshot_file_count(source: str) -> int:
    if source == "ip":
        paths = [tenant_snapshot_dir("ip") if get_current_tenant_slug() else DATA_DIR / "snapshot"]
    elif source == "nvr":
        paths = [tenant_snapshot_dir("nvr") if get_current_tenant_slug() else NVR_SNAPSHOT_DIR]
    else:
        paths = [tenant_snapshot_dir("dvr") if get_current_tenant_slug() else DVR_SNAPSHOT_DIR]

    total = 0
    for path in paths:
        try:
            if path.exists():
                total += sum(1 for item in path.glob("*.jpg") if item.is_file())
        except Exception:
            continue
    return total


def _recorders_count(rows: Iterable[Dict[str, Any]]) -> int:
    keys: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        host = _text(row.get("host") or row.get("ip"))
        port = _text(row.get("http_port") or "80")
        if host:
            keys.add(f"{host}:{port}")
    return len(keys)


def _sites(rows: Iterable[Dict[str, Any]]) -> List[str]:
    names: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = _text(row.get("site_name") or row.get("site") or row.get("local") or row.get("LOCAL"))
        if name and name.upper() != "GERAL":
            names.add(name)
    return sorted(names, key=str.casefold)


def _site_summary(rows: Iterable[Dict[str, Any]], *, resolve_local_snapshots: bool = False) -> List[Dict[str, Any]]:
    by_site: Dict[str, Dict[str, int]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        site = _text(row.get("site_name") or row.get("site") or row.get("local") or row.get("LOCAL"))
        if not site or site.upper() == "GERAL":
            site = "Sem local"
        item = by_site.setdefault(
            site,
            {"total": 0, "online": 0, "offline": 0, "unknown": 0, "missing_snapshot": 0, "missing_local": 0},
        )
        item["total"] += 1
        if _is_online(row):
            item["online"] += 1
        elif _is_offline(row):
            item["offline"] += 1
        else:
            item["unknown"] += 1
        if not _has_snapshot(row, resolve_local=resolve_local_snapshots):
            item["missing_snapshot"] += 1
        if not _has_local(row):
            item["missing_local"] += 1

    rows_out = [{"site": site, **counts} for site, counts in by_site.items()]
    rows_out.sort(key=lambda item: (-int(item.get("offline") or 0), -int(item.get("missing_snapshot") or 0), str(item.get("site") or "").casefold()))
    return rows_out


def _mtime_item(path: Path, label: str, kind: str) -> Dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        ts = path.stat().st_mtime
    except Exception:
        return None
    return {
        "label": label,
        "kind": kind,
        "path": str(path),
        "updated_at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
    }


def _recent_activity() -> List[Dict[str, Any]]:
    if get_current_tenant_slug():
        candidates = [
            _mtime_item(tenant_scoped_path("cam-inventory.json"), "Inventario IP", "inventory"),
            _mtime_item(tenant_scoped_path("cam-inventory-switch.json"), "Inventario Switch", "inventory"),
            _mtime_item(tenant_recorder_inventory_path("dvr"), "Inventario DVR", "inventory"),
            _mtime_item(tenant_recorder_inventory_path("nvr"), "Inventario NVR", "inventory"),
            _mtime_item(tenant_scoped_path("settings.json"), "Configuracoes", "settings"),
        ]
        try:
            kmz_dir = tenant_kmz_output_dir()
            if kmz_dir.exists():
                for item in sorted(kmz_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
                    candidates.append(_mtime_item(item, f"KMZ {item.name}", "kmz"))
        except Exception:
            pass
        rows = [item for item in candidates if item]
        rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return rows[:8]

    candidates = [
        _mtime_item(INVENTORY_JSON_PATH, "Inventario IP", "inventory"),
        _mtime_item(DATA_DIR / "cam-inventory-switch.json", "Inventario Switch", "inventory"),
        _mtime_item(DVR_INVENTORY_JSON_PATH, "Inventario DVR", "inventory"),
        _mtime_item(NVR_INVENTORY_JSON_PATH, "Inventario NVR", "inventory"),
        _mtime_item(DATA_DIR / "app_settings.json", "Configuracoes", "settings"),
    ]
    try:
        if KMZ_OUTPUT_DIR.exists():
            for item in sorted(KMZ_OUTPUT_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
                candidates.append(_mtime_item(item, f"KMZ {item.name}", "kmz"))
    except Exception:
        pass
    rows = [item for item in candidates if item]
    rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return rows[:8]


def build_dashboard_summary() -> Dict[str, Any]:
    settings = get_settings()
    ip_basic_rows = load_inventory_json(mode="basic") or []
    ip_olt_rows = load_inventory_json(mode="olt") or []
    ip_switch_rows = load_inventory_json(mode="switch") or []
    dvr_rows = _recorder_rows("dvr")
    nvr_rows = _recorder_rows("nvr")
    windows_rows = load_windows_inventory()

    # basico/olt/switch sao 3 vistas (potencialmente sobrepostas) da MESMA
    # camera, nao 3 listas que se somam -- concatenar direto contava a
    # mesma camera ate 3x quando os modos tinham dados coincidentes, e
    # inflava ainda mais o card do Dashboard vs a tela Cameras IP real.
    seen_ip_keys: set[str] = set()
    ip_rows: list[dict[str, Any]] = []
    for row in list(ip_basic_rows) + list(ip_olt_rows) + list(ip_switch_rows):
        if not isinstance(row, dict):
            continue
        key = inventory_row_key(row, fallback=f"ROW:{id(row)}")
        if key in seen_ip_keys:
            continue
        seen_ip_keys.add(key)
        ip_rows.append(row)
    all_rows = list(ip_rows) + list(dvr_rows) + list(nvr_rows) + list(windows_rows)
    site_names = _sites(all_rows)

    ip_status = _status_counts(ip_rows)
    dvr_status = _status_counts(dvr_rows)
    nvr_status = _status_counts(nvr_rows)
    windows_status = _status_counts(windows_rows)

    ip_gaps = _missing_counts(ip_rows, resolve_local_snapshots=True)
    recorder_gaps = _missing_counts(list(dvr_rows) + list(nvr_rows))

    alerts = []
    if ip_gaps["missing_snapshot"]:
        alerts.append({"level": "warning", "label": "Cameras IP sem snapshot", "count": ip_gaps["missing_snapshot"]})
    if ip_gaps["missing_local"] + recorder_gaps["missing_local"]:
        alerts.append({"level": "info", "label": "Itens sem local", "count": ip_gaps["missing_local"] + recorder_gaps["missing_local"]})
    offline_total = ip_status["offline"] + dvr_status["offline"] + nvr_status["offline"]
    offline_total += windows_status["offline"]
    if offline_total:
        alerts.append({"level": "danger", "label": "Itens offline ou com erro", "count": offline_total})
    duplicate_ips = _duplicate_count(ip_rows, ("ip", "host"))
    duplicate_macs = _duplicate_count(ip_rows, ("mac", "MAC"))
    if duplicate_ips or duplicate_macs:
        alerts.append({"level": "warning", "label": "Possiveis duplicidades IP/MAC", "count": duplicate_ips + duplicate_macs})
    windows_without_ssd = sum(
        1
        for row in windows_rows
        if isinstance(row, dict) and str(row.get("status") or "").lower() == "online" and not bool(row.get("has_ssd"))
    )
    if windows_without_ssd:
        alerts.append({"level": "info", "label": "Computadores Windows sem SSD detectado", "count": windows_without_ssd})

    try:
        from app.services.monitoring_service import monitoring_summary
        monitoring = monitoring_summary()
    except Exception:
        monitoring = {"ok": False, "types": {}, "events": []}

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app": {
            "name": settings.app_name,
            "version": settings.app_version,
            "env": settings.app_env,
            "docs_enabled": settings.enable_docs,
            "auth_required": settings.auth_required,
        },
        "database": database_runtime_status(),
        "inventory": {
            "ip": {
                **ip_status,
                **ip_gaps,
                "basic_inventory_total": len(ip_basic_rows),
                "olt_inventory_total": len(ip_olt_rows),
                "switch_inventory_total": len(ip_switch_rows),
                "duplicate_ips": duplicate_ips,
                "duplicate_macs": duplicate_macs,
                "snapshot_files": _snapshot_file_count("ip"),
            },
            "dvr": {
                **dvr_status,
                **_missing_counts(dvr_rows),
                "recorders": _recorders_count(dvr_rows),
                "snapshot_files": _snapshot_file_count("dvr"),
            },
            "nvr": {
                **nvr_status,
                **_missing_counts(nvr_rows),
                "recorders": _recorders_count(nvr_rows),
                "snapshot_files": _snapshot_file_count("nvr"),
            },
            "windows": {
                **windows_status,
                "with_ssd": sum(1 for row in windows_rows if isinstance(row, dict) and bool(row.get("has_ssd"))),
                "without_ssd": windows_without_ssd,
            },
        },
        "totals": {
            "items": len(all_rows),
            "online": ip_status["online"] + dvr_status["online"] + nvr_status["online"] + windows_status["online"],
            "offline": offline_total,
            "unknown": ip_status["unknown"] + dvr_status["unknown"] + nvr_status["unknown"] + windows_status["unknown"],
            "sites": len(site_names),
            "snapshots": _snapshot_file_count("ip") + _snapshot_file_count("dvr") + _snapshot_file_count("nvr"),
        },
        "sites": site_names[:20],
        "site_summary": _site_summary(ip_rows, resolve_local_snapshots=True),
        "alerts": alerts,
        "recent_activity": _recent_activity(),
        "monitoring": monitoring,
    }
