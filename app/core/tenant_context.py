from __future__ import annotations

from contextvars import ContextVar, Token
from pathlib import Path

from app.core.paths import DATA_DIR

_tenant_slug_ctx: ContextVar[str] = ContextVar("tenant_slug", default="")


def set_current_tenant_slug(slug: str) -> Token:
    return _tenant_slug_ctx.set(str(slug or "").strip().lower())


def reset_current_tenant_slug(token: Token) -> None:
    _tenant_slug_ctx.reset(token)


def get_current_tenant_slug() -> str:
    return str(_tenant_slug_ctx.get() or "").strip().lower()


def tenant_scoped_key(base_key: str, slug: str = "") -> str:
    tenant_slug = str(slug or get_current_tenant_slug() or "").strip().lower()
    if not tenant_slug:
        return str(base_key or "").strip()
    return f"{str(base_key or '').strip()}__tenant__{tenant_slug}"


def tenant_data_dir(slug: str = "") -> Path:
    tenant_slug = str(slug or get_current_tenant_slug() or "").strip().lower()
    if not tenant_slug:
        return DATA_DIR
    p = DATA_DIR / "tenants" / tenant_slug
    p.mkdir(parents=True, exist_ok=True)
    return p


def tenant_scoped_path(filename: str, slug: str = "") -> Path:
    return tenant_data_dir(slug) / str(filename or "").strip()


def tenant_ip_inventory_path(mode: str = "olt", slug: str = "") -> Path:
    filename = "cam-inventory-switch.json" if str(mode or "").strip().lower() == "switch" else "cam-inventory.json"
    return tenant_scoped_path(filename, slug)


def tenant_recorder_inventory_path(source: str, slug: str = "") -> Path:
    src = str(source or "").strip().lower()
    filename = "nvr-inventory.json" if src == "nvr" else "dvr-inventory.json"
    return tenant_scoped_path(filename, slug)


def tenant_snapshot_dir(source: str, slug: str = "") -> Path:
    src = str(source or "").strip().lower()
    if src == "nvr":
        filename = "nvr_snapshot"
    elif src == "dvr":
        filename = "dvr_snapshot"
    else:
        filename = "snapshot"
    p = tenant_scoped_path(filename, slug)
    p.mkdir(parents=True, exist_ok=True)
    return p


def tenant_report_logo_path(kind: str, slug: str = "") -> Path:
    base = tenant_scoped_path("input", slug)
    base.mkdir(parents=True, exist_ok=True)
    name = str(kind or "inventory").strip().lower()
    if name == "dvr":
        return base / "dvr-report-logo.png"
    if name == "nvr":
        return base / "nvr-report-logo.png"
    return base / "inventory-report-logo.png"


def tenant_input_dir(slug: str = "") -> Path:
    p = tenant_scoped_path("input", slug)
    p.mkdir(parents=True, exist_ok=True)
    return p


def tenant_kmz_input_dir(slug: str = "") -> Path:
    p = tenant_input_dir(slug) / "kmz"
    p.mkdir(parents=True, exist_ok=True)
    return p


def tenant_kmz_imported_path(slug: str = "") -> Path:
    return tenant_input_dir(slug) / "imported.kmz"


def tenant_kmz_imported_geojson_path(slug: str = "") -> Path:
    return tenant_input_dir(slug) / "imported.geojson"


def tenant_kmz_output_dir(slug: str = "") -> Path:
    p = tenant_scoped_path("kmz", slug)
    p.mkdir(parents=True, exist_ok=True)
    return p


def tenant_locations_apply_report_path(slug: str = "") -> Path:
    return tenant_input_dir(slug) / "locations_apply_report.json"
