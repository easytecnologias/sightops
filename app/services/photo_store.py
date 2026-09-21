from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core.paths import DATA_DIR, SAIDA_DIR
from app.core.tenant_context import get_current_tenant_slug, tenant_snapshot_dir


def ip_to_stem(ip: str) -> str:
    s = (ip or "").strip()
    s = s.replace(".", "_").replace(":", "__").replace("/", "_")
    s = re.sub(r"[^0-9A-Za-z_]+", "_", s)
    return s


def snapshot_filename_from_ip(ip: str) -> str:
    return f"{ip_to_stem(ip)}.jpg"


def snapshot_rel_from_ip(ip: str) -> str:
    return f"snapshot/{snapshot_filename_from_ip(ip)}"


def snapshot_url_from_ip(ip: str) -> str:
    return f"/data/snapshot/{snapshot_filename_from_ip(ip)}"


def snapshot_url_from_name(filename: str) -> str:
    return f"/data/snapshot/{Path(filename).name}"


def snapshot_storage_dir() -> Path:
    p = tenant_snapshot_dir("ip") if get_current_tenant_slug() else DATA_DIR / "snapshot"
    p.mkdir(parents=True, exist_ok=True)
    return p


def attach_snapshot_fields(cam: dict[str, Any], ip: str, filename: str) -> None:
    name = Path(filename).name
    cam["snapshot_path"] = f"snapshot/{name}"
    cam["snapshot_url"] = f"/data/snapshot/{name}"
    cam["thumb_url"] = f"/data/snapshot/{name}"


def _candidate_snapshot_paths(name: str) -> list[Path]:
    candidates = []
    if get_current_tenant_slug():
        candidates.append(tenant_snapshot_dir("ip") / name)
    candidates.extend([
        DATA_DIR / "snapshot" / name,
        SAIDA_DIR / "snapshot" / name,
        SAIDA_DIR / "snapshot_manual" / name,
    ])
    return candidates


def resolve_snapshot_file(path_hint: str = "", ip: str = "") -> Path | None:
    raw = str(path_hint or "").strip()
    if raw:
        name = Path(raw).name
        for p in _candidate_snapshot_paths(name):
            if p.exists() and p.is_file():
                return p

    ip_s = str(ip or "").strip()
    if ip_s:
        base_dir = tenant_snapshot_dir("ip") if get_current_tenant_slug() else DATA_DIR / "snapshot"
        fallback = base_dir / snapshot_filename_from_ip(ip_s)
        if fallback.exists() and fallback.is_file():
            return fallback
    return None
