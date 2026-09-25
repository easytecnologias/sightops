from __future__ import annotations

from app.api.endpoints import maintenance


def main() -> None:
    calls: list[dict] = []
    saved: list[tuple[str, list[dict]]] = []

    original = {
        "_load_settings": maintenance._load_settings,
        "_load_ip_rows_by_mode": maintenance._load_ip_rows_by_mode,
        "scripts_zabbix": maintenance.scripts_zabbix,
        "_zabbix_login": maintenance._zabbix_login,
        "_zabbix_api_call": maintenance._zabbix_api_call,
        "save_inventory_json": maintenance.save_inventory_json,
        "_zabbix_tenant_slug": maintenance._zabbix_tenant_slug,
    }

    try:
        maintenance._load_settings = lambda: {
            "zabbix_ip_sync": {
                "url": "http://zabbix.example/api_jsonrpc.php",
                "user": "Admin",
                "pass": "secret",
                "group": "Cameras",
            }
        }
        maintenance._zabbix_tenant_slug = lambda: "easy-tecnologias"
        maintenance._load_ip_rows_by_mode = lambda site="", mode="olt": {
            "basic": [],
            "olt": [{"ip": "10.0.0.1", "status": "unknown"}],
            "switch": [],
        }

        def fake_scripts_zabbix(payload):
            calls.append(dict(payload))
            return {"ok": True, "rows_used": 1}

        def fake_api_call(url, method, params, auth=None, req_id=1):
            if method == "host.get":
                return [
                    {
                        "hostid": "101",
                        "host": "EASY-TECNOLOGIAS-CAM-10.0.0.1",
                        "name": "[EASY-TECNOLOGIAS] Camera (10.0.0.1)",
                        "available": "1",
                        "interfaces": [{"ip": "10.0.0.1", "available": "1"}],
                    }
                ]
            if method == "item.get":
                return [{"hostid": "101", "key_": "icmpping", "lastvalue": "1"}]
            raise AssertionError(method)

        maintenance.scripts_zabbix = fake_scripts_zabbix
        maintenance._zabbix_login = lambda url, user, password: "auth"
        maintenance._zabbix_api_call = fake_api_call
        maintenance.save_inventory_json = lambda rows, mode="olt", **kwargs: saved.append((mode, rows))

        result = maintenance.scripts_zabbix_status_sync({"source": "ip", "mode": "all", "site": ""})
        assert result["ok"] is True, result
        assert result["bootstrapped"] is True, result
        assert result["bootstrap_rows"] == 1, result
        assert result["updated"] == 1 and result["online"] == 1 and result["unknown"] == 0, result
        assert calls and calls[0]["source"] == "ip" and calls[0]["mode"] == "all", calls
        assert saved and saved[0][0] == "olt" and saved[0][1][0]["status"] == "online", saved
    finally:
        for name, value in original.items():
            setattr(maintenance, name, value)

    print("OK zabbix status sync auto-upsert")


if __name__ == "__main__":
    main()
