from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.connector_service import _extract_connector_lans


def main() -> None:
    row = {
        "inventory": {
            "lan_networks": "100.64.8.0/22;10.250.0.0/24;",
            "address_sample": (
                "100.64.10.1/22|BRIDGE DAS CAMERAS;"
                "10.250.0.4/24|sightops-wg;"
                "138.219.201.123/32|INTERNET TELECOM;"
            ),
        }
    }
    lans = _extract_connector_lans(row)
    assert "100.64.8.0/22" in lans, lans
    assert "10.250.0.0/24" not in lans, lans
    assert all(not item.startswith("138.219.") for item in lans), lans
    print("OK connector CGNAT LAN detection", lans)


if __name__ == "__main__":
    main()
