from __future__ import annotations

import os
import re
from typing import Any, Dict
from urllib.parse import urlsplit, urlunsplit

import requests

from app.services.db_store import load_app_settings


def _text(value: Any) -> str:
    return str(value or "").strip()


def _host_safe(value: Any) -> str:
    safe = _text(value).upper()
    safe = re.sub(r"[^A-Z0-9_.-]+", "-", safe)
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "DEFAULT"


def _api_url(raw: Any) -> str:
    value = _text(raw)
    if not value:
        return ""
    parts = urlsplit(value)
    if (parts.hostname or "").lower() in {"10.10.12.51", "zabbix-web", "zabbix-prod-web"}:
        host = os.getenv("SIGHTOPS_ZABBIX_WEB_HOST", "zabbix-prod-web").strip() or "zabbix-prod-web"
        port = os.getenv("SIGHTOPS_ZABBIX_WEB_PORT", "8080").strip() or "8080"
        return urlunsplit((parts.scheme or "http", f"{host}:{port}", "/api_jsonrpc.php", "", ""))
    return value


def _default_zabbix_cfg() -> Dict[str, Any]:
    settings = load_app_settings()
    saved = settings.get("zabbix_ip_sync") if isinstance(settings.get("zabbix_ip_sync"), dict) else {}
    url = (
        _text(saved.get("url"))
        or _text(os.getenv("SIGHTOPS_ZABBIX_URL"))
        or _text(os.getenv("ZBX_URL"))
        or _text(os.getenv("ZABBIX_URL"))
        or "http://zabbix-prod-web:8080/api_jsonrpc.php"
    )
    user = (
        _text(saved.get("user"))
        or _text(os.getenv("SIGHTOPS_ZABBIX_USER"))
        or _text(os.getenv("ZBX_USER"))
        or _text(os.getenv("ZABBIX_USER"))
        or "Admin"
    )
    password = (
        _text(saved.get("pass") or saved.get("password"))
        or _text(os.getenv("SIGHTOPS_ZABBIX_PASS"))
        or _text(os.getenv("ZBX_PASS"))
        or _text(os.getenv("ZABBIX_PASS"))
        or "zabbix"
    )
    return {"url": _api_url(url), "user": user, "pass": password}


def _call(url: str, method: str, params: Any, auth: str | None = None, req_id: int = 1) -> Any:
    body: Dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}
    if auth:
        body["auth"] = auth
    response = requests.post(url, json=body, timeout=45)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(f"{method}: {data['error']}")
    return data.get("result")


def _login(url: str, user: str, password: str) -> str:
    return _text(_call(url, "user.login", {"username": user, "password": password}, req_id=1))


def _tenant_hostgroup_name(tenant_slug: str) -> str:
    return f"Cameras - {_host_safe(tenant_slug)}"


def _tenant_usergroup_name(tenant_slug: str) -> str:
    return f"Cliente - {_host_safe(tenant_slug)}"


def _ensure_hostgroup(url: str, auth: str, name: str) -> str:
    rows = _call(url, "hostgroup.get", {"output": ["groupid", "name"], "filter": {"name": [name]}}, auth, 10) or []
    if rows:
        return _text(rows[0].get("groupid"))
    created = _call(url, "hostgroup.create", {"name": name}, auth, 11) or {}
    return _text((created.get("groupids") or [""])[0])


def _viewer_roleid(url: str, auth: str) -> str:
    roles = _call(url, "role.get", {"output": ["roleid", "name"], "sortfield": "name"}, auth, 20) or []
    preferred = ("user role", "guest role")
    for wanted in preferred:
        for role in roles:
            if _text(role.get("name")).lower() == wanted:
                return _text(role.get("roleid"))
    for role in roles:
        name = _text(role.get("name")).lower()
        if "super" not in name and "admin" not in name:
            return _text(role.get("roleid"))
    return "1"


def _ensure_usergroup(url: str, auth: str, name: str, hostgroupid: str) -> str:
    rights = [{"id": hostgroupid, "permission": 2}]
    rows = _call(url, "usergroup.get", {"output": ["usrgrpid", "name"], "filter": {"name": [name]}}, auth, 30) or []
    if rows:
        usrgrpid = _text(rows[0].get("usrgrpid"))
        _call(
            url,
            "usergroup.update",
            {"usrgrpid": usrgrpid, "hostgroup_rights": rights, "gui_access": 0, "users_status": 0},
            auth,
            31,
        )
        return usrgrpid
    created = _call(
        url,
        "usergroup.create",
        {"name": name, "hostgroup_rights": rights, "gui_access": 0, "users_status": 0},
        auth,
        32,
    ) or {}
    return _text((created.get("usrgrpids") or [""])[0])


def _ensure_user(
    url: str,
    auth: str,
    username: str,
    password: str,
    usergroupid: str,
    roleid: str,
    tenant_name: str,
) -> str:
    rows = _call(url, "user.get", {"output": ["userid", "username"], "filter": {"username": [username]}}, auth, 40) or []
    payload = {
        "username": username,
        "name": tenant_name or username,
        "surname": "SightOps",
        "roleid": roleid,
        "usrgrps": [{"usrgrpid": usergroupid}],
        "timezone": "America/Sao_Paulo",
    }
    if rows:
        userid = _text(rows[0].get("userid"))
        update_payload = {"userid": userid, **payload}
        if password:
            update_payload["passwd"] = password
        _call(url, "user.update", update_payload, auth, 41)
        return userid
    if len(password) < 8:
        raise ValueError("senha do usuario Zabbix precisa ter no minimo 8 caracteres")
    created = _call(url, "user.create", {**payload, "passwd": password}, auth, 42) or {}
    return _text((created.get("userids") or [""])[0])


def provision_zabbix_tenant_access(
    *,
    tenant_slug: str,
    tenant_name: str,
    username: str,
    password: str = "",
) -> Dict[str, Any]:
    slug = _text(tenant_slug).lower()
    if not slug:
        raise ValueError("tenant_slug obrigatorio")
    zbx_user = _text(username)
    if not zbx_user:
        raise ValueError("usuario Zabbix obrigatorio")

    cfg = _default_zabbix_cfg()
    url = _api_url(cfg.get("url"))
    admin_user = _text(cfg.get("user"))
    admin_pass = _text(cfg.get("pass"))
    if not (url and admin_user and admin_pass):
        raise ValueError("Zabbix nao configurado")

    auth = _login(url, admin_user, admin_pass)
    hostgroup_name = _tenant_hostgroup_name(slug)
    usergroup_name = _tenant_usergroup_name(slug)
    hostgroupid = _ensure_hostgroup(url, auth, hostgroup_name)
    usergroupid = _ensure_usergroup(url, auth, usergroup_name, hostgroupid)
    roleid = _viewer_roleid(url, auth)
    userid = _ensure_user(url, auth, zbx_user, _text(password), usergroupid, roleid, _text(tenant_name) or slug)
    return {
        "ok": True,
        "tenant_slug": slug,
        "zabbix_user": zbx_user,
        "zabbix_userid": userid,
        "zabbix_usergroup": usergroup_name,
        "zabbix_usergroupid": usergroupid,
        "zabbix_hostgroup": hostgroup_name,
        "zabbix_hostgroupid": hostgroupid,
        "zabbix_roleid": roleid,
    }
