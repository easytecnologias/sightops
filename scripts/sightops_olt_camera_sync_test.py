from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import olt_service


def main() -> None:
    assert olt_service._full_onu_serial("0A4FCEA8", "ITBS") == "ITBS0A4FCEA8"
    cameras = [{
        "ip": "10.10.11.47",
        "mac": "30:e1:f1:1a:9b:a3",
        "titulo": "28 - FRONTAL LDE 03",
        "snapshot_url": "/data/snapshot/test.jpg",
        "pon": "7",
        "onu_id": "7",
        "onu_name": "gpon 7 onu 7",
        "onu_serial": "0A4FCEA8",
    }]
    saved: list[dict] = []
    old_load = olt_service.load_inventory_json
    old_save = olt_service.save_inventory_json
    try:
        olt_service.load_inventory_json = lambda mode="olt": [dict(row) for row in cameras]
        olt_service.save_inventory_json = lambda rows, mode="olt": saved.extend(dict(row) for row in rows)
        result = olt_service._sync_camera_inventory_from_olt_rows([{
            "cpe_mac": "30:e1:f1:1a:9b:a3",
            "pon": 7,
            "onu_id": 4,
            "onu_name": "gpon 7 onu 4",
            "onu_serial": "ITBS0A4FCEA8",
            "olt_ip": "10.80.80.5",
            "olt_name": "OLT PERUCABA",
            "vlan": 3000,
        }])
    finally:
        olt_service.load_inventory_json = old_load
        olt_service.save_inventory_json = old_save

    assert result["updated_cameras"] == 1, result
    assert saved[0]["onu_id"] == "4", saved
    assert saved[0]["onu_name"] == "gpon 7 onu 4", saved
    assert saved[0]["onu_serial"] == "ITBS0A4FCEA8", saved
    assert saved[0]["titulo"] == "28 - FRONTAL LDE 03", saved
    assert saved[0]["snapshot_url"] == "/data/snapshot/test.jpg", saved
    print("OK OLT->cameras: topologia atualizada por MAC e dados da camera preservados")


if __name__ == "__main__":
    main()
