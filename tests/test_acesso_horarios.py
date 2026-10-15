"""Aba Acesso: horarios, grupos em cartao e a simulacao contra passagens reais.
SQLite temporario, pessoas ficticias, nenhum leitor."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core import tenant_context
from app.services import access_control_horarios as H
from app.services import access_control_store as S
from app.services import db_store

SEG = {"1": [["06:30", "12:30"]], "2": [["06:30", "12:30"]], "3": [["06:30", "12:30"]],
       "4": [["06:30", "12:30"]], "5": [["06:30", "12:30"]]}


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug("escola-teste")
    S.ensure_access_control_schema()
    yield
    tenant_context.reset_current_tenant_slug(token)


def test_horario_junta_faixas_e_respeita_limite_do_leitor(banco):
    h = H.salvar_horario({"nome": "Manha", "dias": {"1": [["08:00", "10:00"], ["06:30", "08:00"]]}})
    assert h["dias"]["1"] == [["06:30", "10:00"]]          # encostadas viram uma
    with pytest.raises(ValueError):
        H.salvar_horario({"nome": "X", "dias": {"1": [["10:00", "09:00"]]}})
    with pytest.raises(ValueError):
        H.salvar_horario({"nome": "X", "dias": {"1": [[f"{h:02d}:00", f"{h:02d}:30"] for h in range(7)]}})
    with pytest.raises(ValueError):
        H.salvar_horario({"nome": "X", "dias": {"2": [["7:00", "08:00"]]}})


def _cenario():
    ent = S.save_device({"name": "ENTRADA", "site": "ESCOLA", "vendor": "intelbras", "host": "192.168.1.201", "password": "x"})
    sai = S.save_device({"name": "SAIDA", "site": "ESCOLA", "vendor": "intelbras", "host": "192.168.1.202", "password": "x",
                         "access_direction": "saida"})
    p = S.save_person({"full_name": "ALUNO FICTICIO", "person_type": "student", "document_id": "52998224725",
                       "enrollment_code": "9001", "site": "ESCOLA", "controller_user_id": "9001"})
    return ent, sai, p


def test_cartao_cria_portas_e_regra_sem_mexer_em_membros(banco):
    ent, sai, p = _cenario()
    r = H.salvar_grupo({"nome": "Alunos manha", "site": "ESCOLA", "portas": [ent["id"]], "ativo": True})
    S.set_group_members(r["id"], [p["id"]])
    h = H.salvar_horario({"nome": "Turno manha", "dias": SEG})
    H.salvar_grupo({"id": r["id"], "nome": "Alunos manha", "site": "ESCOLA", "portas": [ent["id"], sai["id"]],
                    "horario_id": h["id"], "saida_livre": True})
    a = H.acesso()
    g = a["grupos"][0]
    assert sorted(g["portas"]) == sorted([ent["id"], sai["id"]]) and g["horario_id"] == h["id"] and g["membros"] == 1
    assert len([x for x in S.list_rules() if x["active"]]) == 1      # uma regra, nao duas
    assert S.list_provision_status_for_person(p["id"]) == []          # nada enfileirado para o leitor
    with pytest.raises(ValueError):
        H.excluir_horario(h["id"])                                    # em uso
    with pytest.raises(ValueError):
        H.excluir_grupo(r["id"])                                      # ainda tem pessoa


def _passagem(device, pessoa, quando, tipo="entrada"):
    with db_store._conn() as c:
        c.execute("INSERT INTO access_events(id, tenant_slug, site, device_id, person_id, event_type, occurred_at) "
                  "VALUES(?, ?, ?, ?, ?, ?, ?)",
                  (f"e{quando}{tipo}{device['id']}", "escola-teste", "ESCOLA", device["id"], pessoa["id"], tipo, quando))


def test_simulacao_barra_fora_do_horario_e_libera_saida(banco):
    ent, sai, p = _cenario()
    h = H.salvar_horario({"nome": "Turno manha", "dias": SEG})
    r = H.salvar_grupo({"nome": "Alunos manha", "site": "ESCOLA", "portas": [ent["id"], sai["id"]],
                        "horario_id": h["id"], "saida_livre": True})
    S.set_group_members(r["id"], [p["id"]])
    # 2026-10-12 e segunda-feira; 2026-10-11 domingo
    _passagem(ent, p, "2026-10-12 07:10:00")           # dentro
    _passagem(ent, p, "2026-10-12 13:05:00")           # fora: barrada
    _passagem(sai, p, "2026-10-12 13:06:00", "saida")  # saida livre: passa
    _passagem(ent, p, "2026-10-11 09:00:00")           # domingo: barrada
    agora = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    s = H.simular(dias=7, agora=agora)
    assert (s["analisadas"], s["liberadas"], s["barradas"]) == (4, 2, 2)
    assert s["barradas_entrada"] == 2 and s["barradas_saida"] == 0 and s["pessoas_afetadas"] == 1
    assert {b["quando"] for b in s["lista_barradas"]} == {"2026-10-12 13:05:00", "2026-10-11 09:00:00"}
    # feriado na segunda: sem faixa no feriado, a entrada das 07:10 tambem cairia
    H.salvar_feriados("ESCOLA", [{"data": "2026-10-12", "nome": "Nossa Senhora Aparecida"}])
    s2 = H.simular(dias=7, agora=agora)
    assert s2["barradas"] == 3 and any(b["feriado"] for b in s2["lista_barradas"])


def test_simulacao_aponta_porta_que_nenhum_grupo_abre(banco):
    ent, sai, p = _cenario()
    r = H.salvar_grupo({"nome": "So entrada", "site": "ESCOLA", "portas": [ent["id"]]})
    S.set_group_members(r["id"], [p["id"]])
    _passagem(sai, p, "2026-10-13 12:00:00", "saida")
    s = H.simular(dias=7, agora=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc))
    assert s["fora_das_portas"] == 1 and s["lista_fora"][0]["porta"] == "SAIDA"
