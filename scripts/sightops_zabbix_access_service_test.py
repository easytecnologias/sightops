from __future__ import annotations

from app.services import zabbix_access_service as svc


def main() -> None:
    calls: list[tuple[str, object]] = []

    original_cfg = svc._default_zabbix_cfg
    original_call = svc._call

    def fake_call(url, method, params, auth=None, req_id=1):
        calls.append((method, params))
        if method == "user.login":
            return "auth-token"
        if method == "hostgroup.get":
            return [{"groupid": "501", "name": "Cameras - INFORBR"}]
        if method == "role.get":
            return [{"roleid": "1", "name": "User role"}, {"roleid": "3", "name": "Super admin role"}]
        if method == "usergroup.get":
            return []
        if method == "usergroup.create":
            assert params["name"] == "Cliente - INFORBR", params
            assert params["hostgroup_rights"] == [{"id": "501", "permission": 2}], params
            return {"usrgrpids": ["601"]}
        if method == "user.get":
            return []
        if method == "user.create":
            assert params["username"] == "inforbr.viewer", params
            assert params["roleid"] == "1", params
            assert params["usrgrps"] == [{"usrgrpid": "601"}], params
            return {"userids": ["701"]}
        raise AssertionError(method)

    try:
        svc._default_zabbix_cfg = lambda: {"url": "http://zabbix/api_jsonrpc.php", "user": "Admin", "pass": "secret"}
        svc._call = fake_call
        result = svc.provision_zabbix_tenant_access(
            tenant_slug="inforbr",
            tenant_name="InforBr",
            username="inforbr.viewer",
            password="SenhaForte123",
        )
    finally:
        svc._default_zabbix_cfg = original_cfg
        svc._call = original_call

    assert result["zabbix_hostgroup"] == "Cameras - INFORBR", result
    assert result["zabbix_usergroup"] == "Cliente - INFORBR", result
    assert result["zabbix_roleid"] == "1", result
    assert ("usergroup.create", {"name": "Cliente - INFORBR", "hostgroup_rights": [{"id": "501", "permission": 2}], "gui_access": 0, "users_status": 0}) in calls
    print("OK zabbix tenant access provisioning")


if __name__ == "__main__":
    main()
