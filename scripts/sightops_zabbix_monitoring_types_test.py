from __future__ import annotations

import inspect
import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services.zabbix_monitoring_service import sync_monitoring_to_zabbix

    default = inspect.signature(sync_monitoring_to_zabbix).parameters["entity_types"].default
    assert "access_device" in default, f"access_device deveria estar no default, veio {default}"
    assert "whatsapp" in default, f"whatsapp deveria estar no default, veio {default}"
    assert "olt" in default and "onu" in default, "nao pode remover olt/onu do default"
    print("OK: sync_monitoring_to_zabbix inclui access_device e whatsapp por padrao")


if __name__ == "__main__":
    main()
