"""A5: falha ao configurar grupo/host/acao no Zabbix era engolida calada.

SQLite temporario e Zabbix falso (nada sai da maquina)."""
from __future__ import annotations

import logging

import pytest

from app.core import tenant_context
from app.services import db_store
from app.services import zabbix_monitoring_service as Z

TENANT = "cliente-teste"


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug(TENANT)
    db_store.init_db()
    with db_store._conn() as c:
        for i in range(3):
            c.execute(
                "INSERT INTO monitoring_entities(tenant_slug, entity_key, entity_type, display_name, site, status) "
                "VALUES(?,?,?,?,?,?)",
                (TENANT, f"cam:{i}", "camera", f"CAM {i}", "SITE A", "up"),
            )
    monkeypatch.setattr(Z, "_SESSOES", {})
    yield monkeypatch
    tenant_context.reset_current_tenant_slug(token)


def test_falhas_de_grupo_e_host_contadas_e_logadas(banco, caplog):
    linhas = []
    with db_store._conn() as c:
        linhas = [dict(r) for r in c.execute("SELECT * FROM monitoring_entities").fetchall()]
    hosts = [{"hostid": str(i + 1), "host": Z._host_key(TENANT, r), "name": "x"} for i, r in enumerate(linhas)]

    def call(url, method, params, auth=None, req_id=1):
        if method == "user.login":
            return "tok"
        if method == "host.get":
            return hosts
        if method == "hostgroup.get":
            nome = params["filter"]["name"][0]
            return [] if "/" in nome else [{"groupid": "1"}]
        if method == "hostgroup.create":
            raise RuntimeError("sem permissao para criar grupo")
        if method == "host.update":
            raise RuntimeError("macro invalida")
        if method in ("item.get", "trigger.get"):
            return []
        if method == "item.create":
            return {"itemids": [str(100 + i) for i in range(len(params))]}
        if method == "history.push":
            return {"response": "success"}
        return {}

    banco.setattr(Z, "_call", call)
    with caplog.at_level(logging.WARNING, logger="cam-snapshot"):
        r = Z.sync_monitoring_to_zabbix(("camera",))
    assert r["ok"]
    assert r["falhas"]["grupos_site"] == 1          # um site, grupo nao criado (cache evita repetir)
    assert r["falhas"]["hosts_atualizar"] == 3
    assert r["falhas_total"] == 4
    assert "macro invalida" in caplog.text and "sem permissao" in caplog.text
    ultimo = Z.ultimo_sync(TENANT)
    assert ultimo["falhas_total"] == 4 and ultimo["falhas"]["hosts_atualizar"] == 3


def test_acao_do_telegram_que_falha_e_contada(banco, caplog):
    def call(url, method, params, auth=None, req_id=1):
        if method == "mediatype.get":
            return [{"mediatypeid": "5"}]
        if method == "user.get":
            raise RuntimeError("chat invalido")
        return []

    banco.setattr(Z, "_call", call)
    cfg = {"tg_chat_by_site": {"SITE A": "-100", "SITE B": "-200"}}
    grupos = {f"SIGHTOPS - {TENANT.upper()} - CAMERA/SITE A".lower(): "7",
              f"SIGHTOPS - {TENANT.upper()} - CAMERA/SITE B".lower(): "8"}
    with caplog.at_level(logging.WARNING, logger="cam-snapshot"):
        r = Z._configurar_telegram_por_site("http://zbx.test", "tok", TENANT, cfg, grupos, ["camera"])
    assert r == {"acoes": 0, "falhas": 2, "motivo": ""}
    assert "chat invalido" in caplog.text
