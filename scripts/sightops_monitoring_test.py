from __future__ import annotations

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import db_store
from app.services.monitoring_service import list_entities, monitoring_summary, observe_entity
from app.cli.tools.olt_8820i_collect_macs import parse_onu_status


def main() -> None:
    parsed = parse_onu_status("1  ITBSCF6ACC67  Active  OK  -19.87 dBm  -19.14 dBm  0.654  7:22:52:22", 1)
    assert parsed and parsed[0]["serial"] == "ITBSCF6ACC67"
    assert parsed[0]["rx_olt"] == "-19.87" and parsed[0]["rx_onu"] == "-19.14"
    with tempfile.TemporaryDirectory(prefix="sightops-monitoring-") as tmp:
        db_store.SIGHTOPS_DB_PATH = Path(tmp) / "monitoring.db"
        db_store.init_db()
        first = set_current_tenant_slug("cliente-a")
        try:
            item = {"entity_key": "olt:1", "entity_type": "olt", "display_name": "OLT A", "status": "down"}
            assert observe_entity(item)["status"] == "unstable"
            assert observe_entity(item)["status"] == "down"
            assert monitoring_summary()["types"]["olt"]["down"] == 1
        finally:
            reset_current_tenant_slug(first)

        second = set_current_tenant_slug("cliente-b")
        try:
            assert list_entities() == [], "monitoramento vazou entre tenants"
            item = {"entity_key": "olt:1", "entity_type": "olt", "display_name": "OLT B", "status": "up"}
            assert observe_entity(item)["status"] == "up"
            assert list_entities()[0]["display_name"] == "OLT B"
        finally:
            reset_current_tenant_slug(second)
    print("OK monitoring: debounce de falha e isolamento entre tenants")


if __name__ == "__main__":
    main()
