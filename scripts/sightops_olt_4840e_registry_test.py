from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.api.endpoints.olt as olt_endpoint


class _FakeRegistry:
    def __init__(self) -> None:
        self.test_result = None

    def get_olt(self, olt_id: int) -> dict:
        return {
            "id": olt_id,
            "active": True,
            "host": "100.64.10.5",
            "username": "admin",
            "password": "secret",
            "vendor": "Intelbras",
            "model": "4840E",
            "site": "SANTANA",
        }

    def resolve_credentials(self, olt_id: int) -> dict:
        return self.get_olt(olt_id)

    def mark_test_result(self, olt_id: int, ok: bool, detail: str) -> dict:
        self.test_result = {"olt_id": olt_id, "ok": ok, "detail": detail}
        return dict(self.test_result)


def main() -> int:
    registry = _FakeRegistry()
    calls = {"collect": 0, "discover": 0}

    original_registry = olt_endpoint.olt_registry
    original_collect = olt_endpoint.collect_macs
    original_discover = olt_endpoint.discover_onus
    original_get_connector = olt_endpoint.get_connector
    try:
        olt_endpoint.olt_registry = registry
        olt_endpoint.get_connector = lambda *args, **kwargs: None

        def fake_collect(req):
            calls["collect"] += 1
            assert req.olt_ip == "100.64.10.5"
            assert req.olt_model == "4840E"
            return {"ok": True, "rows": [{"cpe_mac": "00:11:22:33:44:55"}]}

        def fake_discover(req):
            calls["discover"] += 1
            return {"ok": True, "pons": {}}

        olt_endpoint.collect_macs = fake_collect
        olt_endpoint.discover_onus = fake_discover

        result = olt_endpoint.api_olt_registry_test(7)
    finally:
        olt_endpoint.olt_registry = original_registry
        olt_endpoint.collect_macs = original_collect
        olt_endpoint.discover_onus = original_discover
        olt_endpoint.get_connector = original_get_connector

    assert result["ok"] is True
    assert result["connected"] is True
    assert result["macs"] == 1
    assert calls == {"collect": 1, "discover": 0}
    assert registry.test_result and registry.test_result["ok"] is True
    print("OK 4840E registry test uses collect_macs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
