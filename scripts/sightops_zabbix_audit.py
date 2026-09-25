from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.endpoints.maintenance import (
    _load_settings,
    _normalize_zabbix_url,
    _zabbix_api_call,
    _zabbix_login,
)


def main() -> None:
    cfg = (_load_settings().get("zabbix_ip_sync") or {})
    url = _normalize_zabbix_url(cfg.get("url"))
    user = str(cfg.get("user") or "")
    password = str(cfg.get("pass") or cfg.get("password") or "")
    print({"configured": bool(url and user and password), "url": url, "user": user})
    if not (url and user and password):
        return
    auth = _zabbix_login(url, user, password)
    groups = _zabbix_api_call(url, "hostgroup.get", {"output": ["groupid", "name"], "sortfield": "name"}, auth, 2) or []
    templates = _zabbix_api_call(url, "template.get", {"output": ["templateid", "host", "name"], "sortfield": "name"}, auth, 3) or []
    hosts = _zabbix_api_call(url, "host.get", {"output": ["hostid", "host", "name", "status"]}, auth, 4) or []
    sightops_hosts = [row for row in hosts if str(row.get("host") or "").startswith("SIGHTOPS.")]
    print("groups", len(groups), groups)
    print("templates", len(templates), templates)
    print("hosts", len(hosts), hosts[:20])
    print("sightops_hosts", len(sightops_hosts), sightops_hosts[:10])


if __name__ == "__main__":
    main()
