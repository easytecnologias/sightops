from __future__ import annotations

import os
import shutil
import tempfile


tmp = tempfile.mkdtemp(prefix="sightops-camera-rec-fallback-")
os.environ["DATA_DIR"] = tmp

try:
    from app.api.endpoints.cameras import api_cameras
    from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug, tenant_recorder_inventory_path
    from app.services.inventory_json import save_inventory_json

    token = set_current_tenant_slug("inforbr")
    try:
        save_inventory_json(
            [
                {
                    "ip": "10.50.11.12",
                    "status": "offline",
                    "local": "TELHA",
                }
            ],
            mode="olt",
        )
        nvr_path = tenant_recorder_inventory_path("nvr")
        nvr_path.parent.mkdir(parents=True, exist_ok=True)
        nvr_path.write_text(
            """[
  {
    "source": "nvr",
    "host": "10.50.10.200",
    "channel": 4,
    "camera_ip": "10.50.11.12",
    "camera_model": "IPC-B121H-C",
    "camera_mac": "8c:22:d2:fa:e9:11",
    "title": "12 - ENTRADA BELAVISTA",
    "local": "TELHA",
    "status": "online",
    "snapshot_url": "/data/nvr_snapshot/10_50_10_200_80_ch04.jpg"
  }
]""",
            encoding="utf-8",
        )

        result = api_cameras(enrich="", mode="olt", site="", connector_id="")
        cameras = result["cameras"]
        assert len(cameras) == 1, cameras
        cam = cameras[0]
        assert cam["ip"] == "10.50.11.12", cam
        assert cam["status"] == "online", cam
        assert cam["direct_status"] == "offline", cam
        assert cam["via_recorder"] is True, cam
        assert cam["recorder_host"] == "10.50.10.200", cam
        assert cam["recorder_channel"] == "4", cam
        assert cam["snapshot_url"].endswith("ch04.jpg"), cam
        assert cam["titulo"] == "12 - ENTRADA BELAVISTA", cam
        assert cam["modelo"] == "IPC-B121H-C", cam
        assert cam["fabricante"] == "Hikvision", cam

        basic = api_cameras(enrich="", mode="basic", site="", connector_id="")
        switch = api_cameras(enrich="", mode="switch", site="", connector_id="")
        assert basic["cameras"] == [], basic
        assert switch["cameras"] == [], switch

        save_inventory_json([], mode="olt")
        empty_olt = api_cameras(enrich="", mode="olt", site="", connector_id="")
        assert empty_olt["cameras"] == [], empty_olt
    finally:
        reset_current_tenant_slug(token)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ok")
