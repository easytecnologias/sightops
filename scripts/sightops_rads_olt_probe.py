from __future__ import annotations

import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.tenant_context import set_current_tenant_slug
from app.services import olt_registry
from app.services.connector_service import list_connectors, list_jobs


def tcp_probe(host: str, port: int, timeout: float = 4.0) -> str:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return "open"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def main() -> None:
    set_current_tenant_slug("rads")
    print("OLTS")
    for olt in olt_registry.list_olts():
        item = dict(olt)
        print(item)
        print("TCP_22", item.get("host"), tcp_probe(str(item.get("host") or ""), 22))
    print("CONNECTORS")
    connectors = list_connectors(include_token=False).get("connectors") or []
    for connector in connectors:
        print(connector)
    print("JOBS")
    print(list_jobs("", limit=20))


if __name__ == "__main__":
    main()
