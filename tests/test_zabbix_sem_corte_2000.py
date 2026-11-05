"""A2: acima de 2000 entidades do tipo, o sync do Zabbix apagava hosts vivos.

SQLite temporario com 2001 ONUs falsas; Zabbix falso (nada sai da maquina)."""
from __future__ import annotations

import pytest

from app.core import tenant_context
from app.services import db_store
from app.services import monitoring_service as MS
from app.services import telegram_notification_service as TG
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
        for i in range(2001):
            c.execute(
                "INSERT INTO monitoring_entities(tenant_slug, entity_key, entity_type, display_name, status) VALUES(?,?,?,?,?)",
                (TENANT, f"onu:{i:05d}", "onu", f"ONU {i:05d}", "up"),
            )
        # outro cliente: nunca entra na lista deste
        c.execute(
            "INSERT INTO monitoring_entities(tenant_slug, entity_key, entity_type, display_name, status) VALUES(?,?,?,?,?)",
            ("outro", "onu:x", "onu", "ONU do outro", "up"),
        )
    yield monkeypatch
    tenant_context.reset_current_tenant_slug(token)


def _zabbix_falso(monkeypatch, hosts):
    apagados: list = []

    def call(url, method, params, auth=None, req_id=1):
        if method == "user.login":
            return "tok"
        if method == "user.checkAuthentication":
            return True
        if method == "host.get":
            return [dict(h) for h in hosts]
        if method == "host.delete":
            apagados.extend(params)
            return {"hostids": params}
        if method in ("hostgroup.get",):
            return [{"groupid": "1"}]
        if method == "item.create":
            return {"itemids": [str(9000 + i) for i in range(len(params))]}
        if method == "history.push":
            return {"response": "success"}
        if method in ("item.get", "trigger.get"):
            return []
        return {}

    monkeypatch.setattr(Z, "_call", call)
    monkeypatch.setattr(Z, "_SESSOES", {})
    return apagados


def _hosts_de(linhas):
    return [{"hostid": str(i + 1), "host": Z._host_key(TENANT, r), "name": "x"} for i, r in enumerate(linhas)]


def test_lista_completa_passa_de_2000(banco):
    linhas, truncada = MS.list_entities_todas(entity_type="onu")
    assert len(linhas) == 2001 and truncada is False
    assert {r["tenant_slug"] for r in linhas} == {TENANT}
    assert len(MS.list_entities(entity_type="onu", limit=5000)) == 2000   # o corte antigo continua para a tela


def test_sync_nao_apaga_host_da_entidade_2001(banco):
    linhas, _ = MS.list_entities_todas(entity_type="onu")
    orfao = {"hostid": "99999", "host": f"SIGHTOPS.{TENANT}.ONU.deadbeefdeadbeef", "name": "sumiu"}
    apagados = _zabbix_falso(banco, _hosts_de(linhas) + [orfao])
    r = Z.sync_monitoring_to_zabbix(("onu",))
    assert r["ok"] and r["total"] == 2001
    assert apagados == ["99999"]          # so o orfao de verdade


def test_lista_cortada_no_teto_nao_apaga_orfao(banco):
    linhas, _ = MS.list_entities_todas(entity_type="onu")
    apagados = _zabbix_falso(banco, _hosts_de(linhas))
    cortada = linhas[:2000]
    banco.setattr(Z, "list_entities_todas", lambda entity_type="": (cortada, True))
    Z.sync_monitoring_to_zabbix(("onu",))
    assert apagados == []                 # a 2001 ficou fora da lista, mas nao e orfa


def test_teto_marca_truncada(banco):
    linhas, truncada = MS.list_entities_todas(entity_type="onu", pagina=700, teto=1500)
    assert len(linhas) == 1500 and truncada is True
    linhas, truncada = MS.list_entities_todas(entity_type="onu", pagina=700, teto=2001)
    assert len(linhas) == 2001 and truncada is False


def test_telegram_ve_todas_as_entidades(banco):
    vistos = []
    banco.setattr(TG, "_state", lambda key, kind: vistos.append(key) or {})
    TG._coletar({"sinal": {}})
    assert len({k for k in vistos}) == 2001
