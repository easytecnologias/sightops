from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from app.services.dashboard_service import build_dashboard_summary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def api_dashboard_summary() -> Dict[str, Any]:
    return build_dashboard_summary()
