"""Regressao: modelo Hikvision deve corrigir fabricante vindo de OUI generico.

Roda direto:
    python scripts/sightops_camera_brand_normalization_test.py
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
    tmp = Path(tempfile.mkdtemp(prefix="sightops-brand-norm-"))
    try:
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["DATA_DIR"] = str(tmp)

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.services.camsnapshot.device_info import _canonicalize_brand_from_model
        from app.services.inventory_json import load_inventory_json, save_inventory_json

        token = set_current_tenant_slug("cliente-a")
        try:
            save_inventory_json(
                [
                    {
                        "ip": "172.16.49.22",
                        "mac": "e0:ca:3c:b4:6a:c2",
                        "fabricante": "Hostone",
                        "modelo": "DS-2CD1021G0-I",
                        "local": "SAN MARINE",
                    },
                    {
                        "ip": "172.16.49.23",
                        "mac": "e0:ca:3c:b1:df:02",
                        "fabricante": "Hostone",
                        "modelo": "",
                        "local": "SAN MARINE",
                    },
                ],
                mode="switch",
            )
            rows = load_inventory_json(mode="switch")
            by_ip = {row["ip"]: row for row in rows}
            check(by_ip["172.16.49.22"]["fabricante"] == "Hikvision", f"modelo DS nao corrigiu fabricante: {rows}")
            check(by_ip["172.16.49.23"]["fabricante"] == "Hostone", f"sem modelo nao deveria inventar fabricante: {rows}")

            probed = _canonicalize_brand_from_model({"modelo": "DS-2CD1021G0-I", "fabricante": "Hostone"})
            check(probed["fabricante"] == "Hikvision", f"probe nao corrigiu fabricante: {probed}")
        finally:
            reset_current_tenant_slug(token)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK camera brand normalization: modelo Hikvision corrige OUI generico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
