from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from app.api.endpoints import olt as olt_endpoint
    from app.services.olt_service import OltCollectMacsRequest

    async def run() -> None:
        olt_endpoint._olt_sync_jobs.clear()
        req = OltCollectMacsRequest(
            host="10.80.80.2",
            username="admin",
            password="secret",
            vendor="Intelbras",
            model="8820i",
            pon="all",
            connector_id="conn-1",
            remote_connector_id="conn-1",
        )
        with (
            patch.object(olt_endpoint, "_ensure_supported_registry_driver", return_value=None),
            patch.object(olt_endpoint, "_registered_request", return_value=req),
            patch.object(olt_endpoint, "_run_olt_registry_sync", new_callable=lambda: _never_run),
        ):
            result = await olt_endpoint.api_olt_registry_sync(123)
        assert result["accepted"] is True, result
        assert result["status"] == "running", result
        assert result["olt_id"] == 123, result
        assert "job_id" in result, result
        for task in list(olt_endpoint._olt_sync_tasks):
            task.cancel()
        await asyncio.gather(*list(olt_endpoint._olt_sync_tasks), return_exceptions=True)
        olt_endpoint._olt_sync_jobs.clear()

    async def _never_run(*args, **kwargs):
        await asyncio.sleep(60)

    asyncio.run(run())
    print("OK OLT registry sync returns async job for all vendors")


if __name__ == "__main__":
    main()
