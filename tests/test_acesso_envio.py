"""Enviar grupo: so cadastra quem falta em cada leitor, sem senha, e nao toca
em quem ja esta. SQLite temporario e leitores falsos."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core import tenant_context
from app.services import access_control_store as S
from app.services import db_store
from app.services.access_control_envio import enviar_faltantes


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug("condo-teste")
    S.ensure_access_control_schema()
    yield
    tenant_context.reset_current_tenant_slug(token)


def test_cadastra_so_quem_falta_sem_senha(banco):
    ent = S.save_device({"name": "ENTRADA", "site": "R", "vendor": "intelbras", "host": "10.0.0.1", "password": "x"})
    acad = S.save_device({"name": "ACADEMIA", "site": "R", "vendor": "intelbras", "host": "10.0.0.2", "password": "x"})
    portas = S.save_door_group({"name": "TODAS", "site": "R"})
    S.set_door_group_members(portas["id"], [ent["id"], acad["id"]])
    g = S.save_group({"name": "GERAL", "site": "R"})
    S.save_rule({"name": "24h", "people_group_id": g["id"], "door_group_id": portas["id"]})
    a = S.save_person({"full_name": "A FICTICIA", "person_type": "resident", "site": "R", "controller_user_id": "10"})
    b = S.save_person({"full_name": "B FICTICIA", "person_type": "resident", "site": "R", "controller_user_id": "11"})
    S.set_group_members(g["id"], [a["id"], b["id"]])
    nos_leitores = {"ENTRADA": [{"controller_user_id": "10"}], "ACADEMIA": [{"controller_user_id": "10"}, {"controller_user_id": "11"}]}
    chamadas = []

    def cadastrar(device, pessoa, foto, **kw):
        chamadas.append((device["name"], pessoa["controller_user_id"], kw))

    r = enviar_faltantes(g["id"], listar=lambda d: nos_leitores[d["name"]], cadastrar=cadastrar,
                         agora=datetime(2026, 10, 15, 17, tzinfo=timezone.utc))
    assert [(c[0], c[1]) for c in chamadas] == [("ENTRADA", "11")]          # so quem faltava
    kw = chamadas[0][2]
    assert kw["senha"] is None and kw["valido_de"] == "2026-10-15 00:00:00" and kw["valido_ate"] == "2036-10-15 23:59:59"
    st = {(x["device_id"], x["status"]) for x in S.list_provision_status_for_person(b["id"])}
    assert (ent["id"], "ok") in st and (acad["id"], "ok") in st
    assert r["ok"] and {x["leitor"]: x["ja_estavam"] for x in r["leitores"]} == {"ENTRADA": 1, "ACADEMIA": 2}


def test_payload_sem_senha_nao_leva_password():
    from app.services import access_control_device as Dev
    enviados = []
    orig = Dev._post_json
    try:
        Dev._post_json = lambda device, path, payload, label: enviados.append(payload) or "OK"
        Dev._provision_intelbras_person({"vendor": "intelbras"}, {"full_name": "X", "controller_user_id": "5"}, None, senha=None)
        Dev._provision_intelbras_person({"vendor": "intelbras"}, {"full_name": "X", "controller_user_id": "5"}, None)
    finally:
        Dev._post_json = orig
    assert "Password" not in enviados[0]["UserList"][0]
    assert enviados[1]["UserList"][0]["Password"] == "123456"           # o envio antigo segue igual


def test_filtro_de_varias_portas_nas_passagens(banco):
    a = S.save_device({"name": "ENTRADA PORTARIA", "site": "R", "vendor": "intelbras", "host": "10.0.0.1", "password": "x"})
    b = S.save_device({"name": "SAIDA PORTARIA", "site": "R", "vendor": "intelbras", "host": "10.0.0.2", "password": "x"})
    c = S.save_device({"name": "ACADEMIA", "site": "R", "vendor": "intelbras", "host": "10.0.0.3", "password": "x"})
    for i, d in enumerate((a, b, c)):
        S.record_event({"site": "R", "device_id": d["id"], "person_name_raw": f"P{i}", "event_type": "entrada",
                        "occurred_at": "2026-10-15 10:0%d:00" % i})
    ev = S.list_access_report_events({"site": "R", "device_ids": [a["id"], b["id"]], "start": "2026-10-15", "end": "2026-10-15"})
    assert sorted(e["device_id"] for e in ev) == sorted([a["id"], b["id"]])
    token = tenant_context.set_current_tenant_slug("outro")
    try:
        assert S.list_access_report_events({"device_ids": [a["id"]], "start": "2026-10-15", "end": "2026-10-15"}) == []
    finally:
        tenant_context.reset_current_tenant_slug(token)


def test_presenca_vale_8_horas_e_vira_saida_nao_registrada(banco):
    """RADS 15/10 22:02: 5 'presentes' na escola vazia."""
    from app.services.access_control_store import access_presence_lists
    ent = S.save_device({"name": "ENTRADA", "site": "E", "vendor": "intelbras", "host": "10.0.0.1", "password": "x"})
    sai = S.save_device({"name": "SAIDA", "site": "E", "vendor": "intelbras", "host": "10.0.0.2", "password": "x"})
    def pessoa(nome, cpf):
        return S.save_person({"full_name": nome, "person_type": "employee", "document_id": cpf, "site": "E"})
    valdice, carlos, saiu = pessoa("VALDICE", "52998224725"), pessoa("CARLOS", "11144477735"), pessoa("SAIU", "39053344705")
    def ev(p, d, t, h):
        S.record_event({"site": "E", "device_id": d["id"], "person_id": p["id"], "person_name_raw": p["full_name"],
                        "event_type": t, "occurred_at": "2026-10-15 " + h})
    ev(valdice, ent, "entrada", "07:28:58"); ev(valdice, ent, "entrada", "09:14:32")      # saiu pela entrada?
    ev(carlos, ent, "entrada", "19:16:06"); ev(carlos, ent, "entrada", "21:18:26")
    ev(saiu, ent, "entrada", "19:00:00"); ev(saiu, sai, "saida", "21:00:00")
    r = access_presence_lists(site="E", agora=datetime(2026, 10, 15, 22, 2))
    assert [x["name"] for x in r["dentro"]] == ["CARLOS"]                     # 21:18, menos de 8 h
    assert [x["name"] for x in r["sem_saida"]] == ["VALDICE"]                 # 09:14, mais de 8 h
    assert r["dentro"][0]["dupla_entrada"] and r["sem_saida"][0]["dupla_entrada"]
    manha = access_presence_lists(site="E", agora=datetime(2026, 10, 16, 6, 0))
    assert manha["dentro"] == [] and {x["name"] for x in manha["sem_saida"]} == {"VALDICE", "CARLOS"}   # dia zerado
    assert access_presence_lists(site="E", agora=datetime(2026, 10, 17, 8, 0)) == {"dentro": [], "sem_saida": []}
