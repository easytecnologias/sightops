"""Regressao: varredura manual deve reabilitar IP removido do sync OLT.

Roda direto:
    python scripts/sightops_manual_scan_restores_ignored_test.py
"""

from __future__ import annotations

import json
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
    tmp = Path(tempfile.mkdtemp(prefix="sightops-manual-scan-"))
    try:
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["DATA_DIR"] = str(tmp)

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.models.requests import ScanRequest
        from app.services.inventory_json import load_inventory_json
        from app.services.olt_ignore_list import add_ignored_rows, list_ignored
        from app.services import scan_service

        token = set_current_tenant_slug("rads")
        original_run = scan_service.subprocess.run
        try:
            ignored_row = {
                "ip": "100.65.10.72",
                "mac": "c4:79:05:94:a3:47",
                "local": "BARRA DE SAO MIGUEL",
                "site": "BARRA DE SAO MIGUEL",
                "remote_connector_id": "barra-connector",
                "olt_ip": "100.65.10.200",
                "pon": "0/1",
                "onu_id": "26",
            }
            check(add_ignored_rows([ignored_row], reason="teste") == 1, "fixture deveria ignorar o IP")
            check(any(row["ip"] == "100.65.10.72" for row in list_ignored()), "IP deveria estar ignorado")

            class FakeProc:
                returncode = 0
                stdout = "ok"
                stderr = ""

            def fake_run(cmd, cwd=None, capture_output=True, text=True, check=False):
                if "--out" not in cmd:
                    return FakeProc()
                out_path = Path(cmd[cmd.index("--out") + 1])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps([
                        {
                            "ip": "100.65.10.72",
                            "mac": "c4:79:05:94:a3:47",
                            "status": "online",
                            "titulo": "1001 - CAMERA DOCUMENTADA",
                            "local": "BARRA DE SAO MIGUEL",
                        }
                    ]),
                    encoding="utf-8",
                )
                return FakeProc()

            scan_service.subprocess.run = fake_run
            result = scan_service.run_http_scan(
                ScanRequest(
                    alvo="100.65.10.72",
                    usuario="admin",
                    senha="senha",
                    inventory_mode="olt",
                    capture_snapshot=False,
                    excel=False,
                )
            )

            rows = load_inventory_json(mode="olt")
            check(result["restored_ignored_count"] == 1, f"scan deveria restaurar 1 ignorado: {result}")
            check(any(row.get("ip") == "100.65.10.72" for row in rows), f"IP deveria voltar ao inventario: {rows}")
            check(not list_ignored(), f"lista de ignorados deveria ficar vazia: {list_ignored()}")
        finally:
            scan_service.subprocess.run = original_run
            reset_current_tenant_slug(token)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK manual scan restores ignored IPs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
