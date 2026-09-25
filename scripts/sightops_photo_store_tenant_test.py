"""Regressao: snapshot de tenant deve salvar/consultar na pasta do tenant.

Roda direto:
    python scripts/sightops_photo_store_tenant_test.py
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
    tmp = Path(tempfile.mkdtemp(prefix="sightops-photo-store-"))
    try:
        os.environ["DATA_DIR"] = str(tmp)

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.services.photo_store import resolve_snapshot_file, snapshot_filename_from_ip, snapshot_storage_dir

        token = set_current_tenant_slug("inforbr")
        try:
            snap_dir = snapshot_storage_dir()
            expected = tmp / "tenants" / "inforbr" / "snapshot"
            check(snap_dir == expected, f"snapshot_storage_dir sem escopo de tenant: {snap_dir}")

            name = snapshot_filename_from_ip("10.50.11.6")
            stored = snap_dir / name
            stored.write_bytes(b"fake-jpeg")
            resolved = resolve_snapshot_file(ip="10.50.11.6")
            check(resolved == stored, f"resolve_snapshot_file nao priorizou tenant: {resolved}")
        finally:
            reset_current_tenant_slug(token)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK photo store: snapshots usam pasta do tenant")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
