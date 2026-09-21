from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from app.models.requests import ScanRequest, InventoryDeleteRequest, RescanSingleIPRequest
from app.services.scan_service import run_http_scan
from app.services.inventory_delete_service import inventory_delete
from app.services.rescan_service import rescan_single_ip

router = APIRouter(prefix="/api", tags=["cameras"])


@router.post("/scan")
def api_scan_route(req: ScanRequest) -> Dict[str, Any]:
    return run_http_scan(req)


@router.post("/inventory/delete")
def api_inventory_delete(req: InventoryDeleteRequest) -> Dict[str, Any]:
    return inventory_delete(req)


@router.post("/rescan-single-ip")
def api_rescan_single_ip(req: RescanSingleIPRequest) -> Dict[str, Any]:
    return rescan_single_ip(req)
