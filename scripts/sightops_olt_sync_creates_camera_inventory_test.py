from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import olt_service
from app.models.requests import OltCollectMacsRequest


def main() -> int:
    saved: dict[str, list[dict]] = {}
    inventory = {
        "olt": [],
        "basic": [{"ip": "10.0.0.10", "mac": "aa:aa:aa:aa:aa:aa", "local": "OUTRO"}],
        "switch": [],
    }

    original_load_inventory = olt_service.load_inventory_json
    original_save_inventory = olt_service.save_inventory_json
    original_list_connectors = olt_service.list_connectors
    original_get_connector = olt_service.get_connector
    original_load_olt_state = olt_service.load_olt_cpe_state
    original_collect_4840e = olt_service.collect_macs_4840e
    try:
        olt_service.load_inventory_json = lambda mode="olt", **_: list(inventory.get(mode, []))

        def fake_save(rows, mode="olt"):
            saved[mode] = list(rows)

        olt_service.save_inventory_json = fake_save
        olt_service.load_olt_cpe_state = lambda: {"cpes": []}
        olt_service.list_connectors = lambda include_token=False: {
            "connectors": [
                {
                    "id": "conn-barra",
                    "site": "BARRA",
                    "inventory": {"arp_sample": "100.65.11.10|30:E1:F1:AA:BB:CC;"},
                },
                {
                    "id": "conn-outra",
                    "site": "OUTRA",
                    "inventory": {"arp_sample": "100.64.11.10|30:E1:F1:AA:BB:CC;"},
                },
            ]
        }
        olt_service.get_connector = lambda *_, **__: {
            "id": "conn-barra",
            "name": "BARRA",
            "site": "BARRA",
            "status": "online",
            "tunnel": {"enabled": True},
        }

        index = olt_service._known_mac_ip_index(connector_id="conn-barra", site="BARRA")
        assert index["30e1f1aabbcc"]["ip"] == "100.65.11.10"

        result = olt_service._sync_camera_inventory_from_olt_rows(
            [
                {
                    "cpe_mac": "30:e1:f1:aa:bb:cc",
                    "ip": index["30e1f1aabbcc"]["ip"],
                    "site": "BARRA",
                    "remote_connector_id": "conn-barra",
                    "pon": "0/1",
                    "onu_id": "7",
                    "onu_serial": "ABC12345",
                    "olt_ip": "192.168.50.2",
                    "olt_name": "OLT - BARRA",
                }
            ]
        )

        assert result["created_cameras"] == 1
        assert result["updated_cameras"] == 0
        assert "olt" in saved
        created = saved["olt"][0]
        assert created["ip"] == "100.65.11.10"
        assert created["local"] == "BARRA"
        assert created["remote_connector_id"] == "conn-barra"
        assert created["pon"] == "0/1"

        inventory["olt"] = []
        saved.clear()
        olt_service.collect_macs_4840e = lambda **_: [
            {"cpe_mac": "30:e1:f1:00:00:01", "pon": "0/1", "onu_id": "1"}
        ]
        try:
            olt_service.collect_macs(
                OltCollectMacsRequest(
                    olt_ip="192.168.50.2",
                    user="admin",
                    password="secret",
                    pon="all",
                    olt_model="4840E",
                    site="BARRA",
                    connector_id="conn-barra",
                    scan_origin="connector",
                )
            )
            raise AssertionError("mismatched connector MACs should fail before saving")
        except Exception as exc:
            assert "MACs coletados nao batem com o conector" in str(exc)
        assert saved == {}
    finally:
        olt_service.load_inventory_json = original_load_inventory
        olt_service.save_inventory_json = original_save_inventory
        olt_service.list_connectors = original_list_connectors
        olt_service.get_connector = original_get_connector
        olt_service.load_olt_cpe_state = original_load_olt_state
        olt_service.collect_macs_4840e = original_collect_4840e
    print("OK OLT sync creates connector-scoped camera inventory rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
