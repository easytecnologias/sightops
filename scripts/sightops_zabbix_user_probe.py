from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.zabbix_access_service import _api_url, _call, _default_zabbix_cfg, _login


def main() -> None:
    username = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("ZBX_PROBE_USER") or "").strip()
    if not username:
        raise SystemExit("usage: sightops_zabbix_user_probe.py <username>")

    cfg = _default_zabbix_cfg()
    url = _api_url(cfg.get("url"))
    auth = _login(url, str(cfg.get("user") or ""), str(cfg.get("pass") or ""))
    users = _call(
        url,
        "user.get",
        {
            "output": [
                "userid",
                "username",
                "name",
                "surname",
                "roleid",
                "attempt_failed",
                "attempt_clock",
                "attempt_ip",
            ],
            "filter": {"username": [username]},
            "selectUsrgrps": ["usrgrpid", "name", "gui_access", "users_status"],
        },
        auth,
        2,
    ) or []

    print("ZABBIX_URL", url)
    print("USER_COUNT", len(users))
    for user in users:
        groups = user.get("usrgrps") or []
        print(
            "USER",
            {
                "userid": user.get("userid"),
                "username": user.get("username"),
                "roleid": user.get("roleid"),
                "attempt_failed": user.get("attempt_failed"),
                "attempt_clock": user.get("attempt_clock"),
                "attempt_ip": user.get("attempt_ip"),
                "groups": [
                    {
                        "usrgrpid": group.get("usrgrpid"),
                        "name": group.get("name"),
                        "gui_access": group.get("gui_access"),
                        "users_status": group.get("users_status"),
                    }
                    for group in groups
                ],
            },
        )

    password = os.getenv("ZBX_PROBE_PASS", "")
    if password:
        try:
            token = _login(url, username, password)
            print("LOGIN_TEST", "ok" if token else "empty-token")
        except Exception as exc:
            print("LOGIN_TEST", f"failed: {exc}")


if __name__ == "__main__":
    main()
