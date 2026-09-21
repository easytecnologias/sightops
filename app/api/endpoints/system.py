from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

from app.core.database_runtime import database_runtime_status
from app.core.settings import get_settings
from app.services.db_store import db_status, init_db, load_app_settings, save_app_settings

router = APIRouter(prefix="/api/system", tags=["system"])
STARTED_AT = datetime.now(timezone.utc).isoformat()


@router.get("/health/live")
def api_system_live() -> Dict[str, Any]:
    settings = get_settings()
    return {
        "ok": True,
        "status": "alive",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
        "started_at": STARTED_AT,
    }


@router.get("/health/ready")
def api_system_ready() -> Dict[str, Any]:
    settings = get_settings()
    db = db_status()
    runtime = database_runtime_status()
    return {
        "ok": True,
        "status": "ready",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
        "database": {
            "backend": settings.database_backend,
            "exists": bool(db.get("exists")),
            "path": db.get("db_path", ""),
            "configured": bool(runtime.get("configured")),
            "reachable": bool(runtime.get("reachable")),
            "detail": runtime.get("detail", ""),
            "host": runtime.get("host", ""),
            "port": runtime.get("port", 0),
            "name": runtime.get("database", ""),
        },
    }


@router.get("/info")
def api_system_info() -> Dict[str, Any]:
    settings = get_settings()
    return {"ok": True, "app": settings.public_dict(), "database_runtime": database_runtime_status()}


def _product_profile() -> Dict[str, str]:
    try:
        obj = load_app_settings()
    except Exception:
        obj = {}
    profile = obj.get("product_profile") if isinstance(obj, dict) else {}
    profile = profile if isinstance(profile, dict) else {}
    return {
        "company_name": str(profile.get("company_name") or "").strip(),
        "license_plan": str(profile.get("license_plan") or "implantacao-assistida").strip(),
        "license_status": str(profile.get("license_status") or "active").strip(),
        "support_contact": str(profile.get("support_contact") or "").strip(),
    }


@router.get("/product")
def api_system_product() -> Dict[str, Any]:
    settings = get_settings()
    return {
        "ok": True,
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "env": settings.app_env,
        "product": _product_profile(),
    }


@router.post("/product")
def api_system_product_save(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    profile = {
        "company_name": str(data.get("company_name") or "").strip()[:120],
        "license_plan": str(data.get("license_plan") or "implantacao-assistida").strip()[:80],
        "license_status": str(data.get("license_status") or "active").strip()[:40],
        "support_contact": str(data.get("support_contact") or "").strip()[:160],
    }
    try:
        obj = load_app_settings()
    except Exception:
        obj = {}
    obj = obj if isinstance(obj, dict) else {}
    obj["product_profile"] = profile
    save_app_settings(obj)
    return {"ok": True, "product": profile}


@router.post("/bootstrap")
def api_system_bootstrap() -> Dict[str, Any]:
    return {"ok": True, "database": init_db()}
