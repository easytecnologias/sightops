from __future__ import annotations

import os
import shutil
import tempfile
import importlib
import sys
from pathlib import Path


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    tmp = Path(tempfile.mkdtemp(prefix="sightops-saas-smoke-"))
    try:
        os.environ["DATA_DIR"] = str(tmp / "data")
        os.environ["SIGHTOPS_DB_PATH"] = str(tmp / "data" / "sightops.db")
        os.environ["ENABLE_LEGACY_STATE_IMPORT"] = "0"
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ.pop("DATABASE_URL", None)

        from app.core.tenant_context import get_current_tenant_slug, reset_current_tenant_slug, set_current_tenant_slug
        db_store = importlib.import_module("app.services.db_store")

        status = db_store.init_db()
        _assert(status.get("backend") == "sqlite", f"smoke deve usar sqlite temporario, recebeu: {status!r}")
        _assert(str(status.get("db_path") or "").startswith(str(tmp)), f"smoke deve usar db temporario, recebeu: {status!r}")
        with db_store._conn() as c:
            cols = [str(r["name"]) for r in c.execute("PRAGMA table_info(ip_cameras)").fetchall()]
        _assert("tenant_slug" in cols, f"schema temporario sem tenant_slug: file={getattr(db_store, '__file__', '')} status={status!r} cols={cols!r}")

        token_a = set_current_tenant_slug("tenant-a")
        try:
            _assert(get_current_tenant_slug() == "tenant-a", "tenant context nao ativou tenant-a")
            db_store.upsert_ip_inventory_rows(
                [
                    {
                        "ip": "10.0.0.20",
                        "title": "CAMERA A",
                        "local": "SITE A",
                        "status": "online",
                        "mac": "aa:aa:aa:aa:aa:aa",
                    }
                ]
            )
            db_store.save_olt_cpe_state({"rows": [{"serial": "ONU-A"}]})
            db_store.save_switch_mac_state({"rows": [{"mac": "aa:aa:aa:aa:aa:aa"}]})
        finally:
            reset_current_tenant_slug(token_a)

        token_b = set_current_tenant_slug("tenant-b")
        try:
            _assert(get_current_tenant_slug() == "tenant-b", "tenant context nao ativou tenant-b")
            db_store.upsert_ip_inventory_rows(
                [
                    {
                        "ip": "10.0.0.20",
                        "title": "CAMERA B",
                        "local": "SITE B",
                        "status": "offline",
                        "mac": "bb:bb:bb:bb:bb:bb",
                    }
                ]
            )
            db_store.save_olt_cpe_state({"rows": [{"serial": "ONU-B"}]})
            db_store.save_switch_mac_state({"rows": [{"mac": "bb:bb:bb:bb:bb:bb"}]})
        finally:
            reset_current_tenant_slug(token_b)

        token_a = set_current_tenant_slug("tenant-a")
        try:
            _assert(get_current_tenant_slug() == "tenant-a", "tenant context de leitura nao ativou tenant-a")
            rows_a = db_store.query_inventory("ip")
            _assert(len(rows_a) == 1, "tenant-a deve enxergar uma camera")
            _assert(rows_a[0]["title"] == "CAMERA A", f"tenant-a vazou camera de outro tenant: {rows_a[0]!r}")
            _assert(db_store.list_sites("ip") == [{"name": "SITE A"}], "tenant-a vazou site de outro tenant")
            _assert(db_store.load_olt_cpe_state()["rows"][0]["serial"] == "ONU-A", "tenant-a vazou OLT state")
            _assert(db_store.load_switch_mac_state()["rows"][0]["mac"].startswith("aa:"), "tenant-a vazou switch state")
            db_store.clear_inventory_source("ip")
            _assert(db_store.query_inventory("ip") == [], "clear do tenant-a nao limpou o proprio tenant")
        finally:
            reset_current_tenant_slug(token_a)

        token_b = set_current_tenant_slug("tenant-b")
        try:
            _assert(get_current_tenant_slug() == "tenant-b", "tenant context de leitura nao ativou tenant-b")
            rows_b = db_store.query_inventory("ip")
            _assert(len(rows_b) == 1, "tenant-b foi apagado por acao de outro tenant")
            _assert(rows_b[0]["title"] == "CAMERA B", "tenant-b perdeu ou misturou camera")
            _assert(db_store.list_sites("ip") == [{"name": "SITE B"}], "tenant-b vazou site")
            _assert(db_store.load_olt_cpe_state()["rows"][0]["serial"] == "ONU-B", "tenant-b vazou OLT state")
            _assert(db_store.load_switch_mac_state()["rows"][0]["mac"].startswith("bb:"), "tenant-b vazou switch state")
        finally:
            reset_current_tenant_slug(token_b)

        print("OK sightops SaaS smoke: tenant inventory, sites, OLT state and switch state isolated")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
