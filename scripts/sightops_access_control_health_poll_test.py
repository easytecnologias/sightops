from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["SIGHTOPS_DB_PATH"] = os.path.join(tmp, "sightops-access-health.db")
        os.environ["SIGHTOPS_SECRET_KEY"] = "sightops-access-health-test-key"

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.services.access_control_store import (
            ensure_access_control_schema,
            list_devices,
            save_device,
        )
        from app.services import access_control_sync

        def _status_of(device_id: str) -> str:
            row = next(d for d in list_devices() if d["id"] == device_id)
            return row["status"]

        token = set_current_tenant_slug("escola-health-test")
        try:
            ensure_access_control_schema()
            device = save_device({
                "name": "Portaria Teste",
                "site": "ESCOLA",
                "host": "10.10.13.200",
                "username": "admin",
                "password": "SenhaTeste2011",
            })
            device_id = device["id"]

            # 1) poll com sucesso marca online
            with patch.object(access_control_sync, "poll_events", return_value=[]):
                access_control_sync.poll_device_events(device_id)
            assert _status_of(device_id) == "online", "deveria marcar online apos sucesso"

            # 2) poll que falha (dispositivo desligado) tem que marcar offline
            with patch.object(
                access_control_sync,
                "poll_events",
                side_effect=HTTPException(status_code=502, detail="Nao foi possivel conectar no IP do dispositivo."),
            ):
                access_control_sync.poll_device_events(device_id)
            status_apos_falha = _status_of(device_id)
            assert status_apos_falha == "offline", f"esperado offline, veio {status_apos_falha!r}"

            # Verificar que last_seen_at foi preenchido (nao blanked)
            device_after_failure = next(d for d in list_devices() if d["id"] == device_id)
            last_seen_at_apos_falha = device_after_failure.get("last_seen_at", "")
            assert last_seen_at_apos_falha, f"last_seen_at deveria ser preenchido, veio vazio"

            print("OK: poll_device_events marca offline quando a consulta falha")
        finally:
            reset_current_tenant_slug(token)


if __name__ == "__main__":
    main()
