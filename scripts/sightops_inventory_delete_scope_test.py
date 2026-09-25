"""Regressao: botoes de apagar devem respeitar site, modo e host.

Roda direto:
    python scripts/sightops_inventory_delete_scope_test.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sightops-delete-scope-"))
    try:
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["DATA_DIR"] = str(tmp)

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.models.requests import InventoryDeleteRequest
        from app.services.inventory_delete_service import inventory_delete
        from app.services.inventory_json import load_inventory_json, save_inventory_json
        from app.services.olt_service import _sync_camera_inventory_from_olt_rows
        from app.api.endpoints import dvr

        token = set_current_tenant_slug("cliente-a")
        try:
            save_inventory_json(
                [
                    {"ip": "10.0.0.10", "local": "SITE A", "titulo": "A"},
                    {"ip": "10.0.0.11", "local": "SITE B", "titulo": "B"},
                ],
                mode="switch",
            )
            result = inventory_delete(
                InventoryDeleteRequest(
                    ips=["10.0.0.10"],
                    keys=["IP:10.0.0.10"],
                    mode="switch",
                    site="SITE B",
                )
            )
            rows = load_inventory_json(mode="switch")
            check(result["removed"] == 0, f"camera de outro site nao deveria remover: {result}")
            check(len(rows) == 2, f"inventario de cameras perdeu linha fora do site: {rows}")

            result = inventory_delete(
                InventoryDeleteRequest(
                    ips=["10.0.0.10"],
                    keys=["IP:10.0.0.10"],
                    mode="switch",
                    site="SITE A",
                )
            )
            rows = load_inventory_json(mode="switch")
            check(result["removed"] == 1, f"camera do site correto deveria remover: {result}")
            check([r["ip"] for r in rows] == ["10.0.0.11"], f"camera errada ficou/removeu: {rows}")

            dvr._write_rows(
                [
                    {"host": "172.16.1.10", "channel": 1, "local": "SITE A", "inventory_mode": "basico"},
                    {"host": "172.16.1.10", "channel": 1, "local": "SITE A", "inventory_mode": "switch"},
                    {"host": "172.16.1.11", "channel": 1, "local": "SITE B", "inventory_mode": "switch"},
                ]
            )
            cleared = dvr.api_dvr_clear(site="SITE A", mode="switch")
            rows = dvr._read_rows()
            check(cleared["removed_rows"] == 1, f"clear DVR switch/site deveria remover 1: {cleared}")
            check(
                {(r["host"], r["channel"], r["local"], r["inventory_mode"]) for r in rows}
                == {
                    ("172.16.1.10", 1, "SITE A", "basico"),
                    ("172.16.1.11", 1, "SITE B", "switch"),
                },
                f"clear DVR removeu fora do escopo: {rows}",
            )

            olt_row = {
                "ip": "100.65.10.72",
                "mac": "c4:79:05:94:a3:47",
                "local": "BARRA DE SAO MIGUEL",
                "site": "BARRA DE SAO MIGUEL",
                "source": "olt-sync",
                "remote": True,
                "remote_connector_id": "barra-connector",
                "connector_id": "barra-connector",
                "olt_ip": "100.65.10.200",
                "pon": "0/1",
                "onu_id": "26",
                "onu_name": "Escola_M",
                "onu_serial": "98:e5:5b:11:22:33",
            }
            save_inventory_json([olt_row], mode="olt")
            result = inventory_delete(
                InventoryDeleteRequest(
                    ips=["100.65.10.72"],
                    keys=[],
                    mode="olt",
                    site="BARRA DE SAO MIGUEL",
                    connector_id="barra-connector",
                    permanent=True,
                )
            )
            check(result["removed"] == 1, f"delete OLT permanente deveria remover 1: {result}")
            recreated = _sync_camera_inventory_from_olt_rows([{
                "ip": "100.65.10.72",
                "cpe_mac": "c4:79:05:94:a3:47",
                "site": "BARRA DE SAO MIGUEL",
                "connector_id": "barra-connector",
                "remote_connector_id": "barra-connector",
                "olt_ip": "100.65.10.200",
                "pon": "0/1",
                "onu_id": "26",
                "onu_name": "Escola_M",
                "onu_serial": "98:e5:5b:11:22:33",
            }])
            check(recreated["created_cameras"] == 0, f"OLT nao deveria recriar IP ignorado: {recreated}")
            check(load_inventory_json(mode="olt") == [], "inventario OLT deveria continuar vazio apos sync")

            save_inventory_json([olt_row], mode="olt")
            pruned = _sync_camera_inventory_from_olt_rows([])
            check(pruned["removed_ignored"] == 1, f"sync deveria podar linha ignorada ja existente: {pruned}")
            check(load_inventory_json(mode="olt") == [], "linha ignorada existente deveria ser removida pelo sync")

            deleted = dvr.api_dvr_delete(
                dvr.RecorderDeleteRequest(
                    items=[{"host": "172.16.1.10", "channel": 1}],
                    mode="switch",
                )
            )
            rows = dvr._read_rows()
            check(deleted["removed"] == 0, f"delete selecionado nao deveria apagar outro modo: {deleted}")
            check(len(rows) == 2, f"delete selecionado removeu modo errado: {rows}")
        finally:
            reset_current_tenant_slug(token)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK inventory delete scope: site, modo e host preservados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
