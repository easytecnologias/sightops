from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.db_store import (
    assign_site,
    db_status,
    init_db,
    list_sites,
    migrate_db_storage,
    migrate_json_to_db,
    query_inventory,
    upsert_site,
)
from app.services.inventory_json import load_inventory_json

router = APIRouter(prefix="/api/db", tags=["database"])


class SiteUpsertRequest(BaseModel):
    name: str
    description: str = ""
    active: bool = True


class AssignSiteRequest(BaseModel):
    source: str = Field(default="ip", pattern="^(ip|dvr|nvr)$")
    site: str
    ip: str = ""
    host: str = ""
    channel: Optional[int] = None


class StorageMigrateRequest(BaseModel):
    source_backend: str = "sqlite"
    target_backend: str = "postgres"
    force: bool = False


@router.get("/status")
def api_db_status() -> Dict[str, Any]:
    return db_status()


@router.post("/init")
def api_db_init() -> Dict[str, Any]:
    return init_db()


@router.post("/migrate")
def api_db_migrate() -> Dict[str, Any]:
    return migrate_json_to_db()


@router.post("/storage/migrate")
def api_db_storage_migrate(req: StorageMigrateRequest) -> Dict[str, Any]:
    try:
        return migrate_db_storage(
            source_backend=req.source_backend,
            target_backend=req.target_backend,
            force=req.force,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="falha ao migrar armazenamento do banco")


@router.get("/sites")
def api_db_sites(source: str = Query("")) -> Dict[str, Any]:
    src = str(source or "").strip().lower()
    if src and src not in ("ip", "dvr", "nvr"):
        raise HTTPException(status_code=400, detail="source invalido (use ip|dvr|nvr)")
    sites = list_sites(src)
    if src == "ip":
        names: set[str] = set()
        for row in load_inventory_json(mode="olt") or []:
            if not isinstance(row, dict):
                continue
            for key in ("site", "site_name", "local", "LOCAL"):
                name = str(row.get(key) or "").strip()
                if name and name.upper() != "GERAL":
                    names.add(name)
                    break
        if not names:
            names = {str(s.get("name") or "").strip() for s in sites if isinstance(s, dict)}
        sites = [{"name": name} for name in sorted((n for n in names if n and n.upper() != "GERAL"), key=str.casefold)]
    return {"ok": True, "source": src, "sites": sites}


@router.post("/sites")
def api_db_upsert_site(req: SiteUpsertRequest) -> Dict[str, Any]:
    try:
        site = upsert_site(req.name, req.description, req.active)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "site": site}


@router.get("/inventory")
def api_db_inventory(
    source: str = Query("ip", pattern="^(ip|dvr|nvr)$"),
    site: str = Query(""),
    only_online: bool = Query(False),
) -> Dict[str, Any]:
    rows = query_inventory(source=source, site=site, only_online=bool(only_online))
    return {"ok": True, "source": source, "site": site, "count": len(rows), "rows": rows}


@router.post("/assign-site")
def api_db_assign_site(req: AssignSiteRequest) -> Dict[str, Any]:
    try:
        out = assign_site(
            req.source,
            req.site,
            ip=str(req.ip or "").strip(),
            host=str(req.host or "").strip(),
            channel=req.channel,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return out
