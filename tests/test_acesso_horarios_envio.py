"""Horarios indo ao leitor: comparar (so le) e enviar. Leitor de mentira que
responde no formato lido dos SS 3532/3540/3542 em 22/10/2026 (7 dias x 4
faixas, 128 indices, setConfig com espaco em %20)."""
from __future__ import annotations

from urllib.parse import parse_qsl

import pytest

from app.core import tenant_context
from app.services import access_control_horarios as H
from app.services import access_control_horarios_envio as E
from app.services import access_control_store as S
from app.services import db_store

SEG_SEX = {str(d): [["06:30", "12:30"]] for d in range(1, 6)}


class Resp:
    def __init__(self, text, status_code=200):
        self.text, self.status_code = text, status_code


class LeitorFalso:
    def __init__(self, usuarios):
        self.cfg = {}
        for i in range(E.INDICES):
            self.cfg[f"AccessTimeSchedule[{i}].Enable"] = "true" if i == 0 else "false"
            for d in range(7):
                for s in range(4):
                    self.cfg[f"AccessTimeSchedule[{i}].TimeSchedule[{d}][{s}]"] = (
                        "1 00:00:00-23:59:59" if s == 0 else "1 00:00:00-00:00:00")
        self.usuarios = {u: {"nome": n, "ts": [0]} for u, n in usuarios.items()}
        self.escritas = []

    def get(self, device, path, params=None):
        if params is None and "?" in path:
            path, query = path.split("?", 1)
            assert "+" not in query, "espaco tem de ir como %20"
            params = dict(parse_qsl(query))
        params = params or {}
        if path.endswith("configManager.cgi") and params.get("action") == "getConfig":
            return Resp("\r\n".join(f"table.{k}={v}" for k, v in self.cfg.items() if k.startswith(params["name"] + "[")))
        if path.endswith("configManager.cgi") and params.get("action") == "setConfig":
            pares = {k: v for k, v in params.items() if k != "action"}
            if len(pares) > 12:
                return Resp("Error\r\nNot Implemented!", 501)
            self.escritas.append(pares)
            self.cfg.update(pares)
            return Resp("OK")
        if path.endswith("recordFinder.cgi"):
            linhas = [f"found={len(self.usuarios)}"]
            for n, (uid, u) in enumerate(sorted(self.usuarios.items())):
                linhas += [f"records[{n}].UserID={uid}", f"records[{n}].CardName={u['nome']}", f"records[{n}].Doors[0]=0"]
                linhas += [f"records[{n}].TimeSections[{k}]={v}" for k, v in enumerate(u["ts"])]
            return Resp("\r\n".join(linhas))
        raise AssertionError(f"pedido inesperado {path} {params}")

    def post(self, device, path, payload, rotulo):
        assert path == "/cgi-bin/AccessUser.cgi?action=updateMulti"
        for u in payload["UserList"]:
            assert set(u) == {"UserID", "TimeSections"}, "so troca o horario, nada mais"
            self.usuarios[u["UserID"]]["ts"] = list(u["TimeSections"])
        self.escritas.append(payload)
        return "OK"


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


def _cenario():
    ent = S.save_device({"name": "ENTRADA", "site": "ESCOLA", "vendor": "intelbras", "host": "192.168.1.201", "password": "x"})
    a = S.save_person({"full_name": "ALUNO MANHA", "person_type": "student", "document_id": "52998224725",
                       "enrollment_code": "9001", "site": "ESCOLA", "controller_user_id": "9001"})
    b = S.save_person({"full_name": "PROFESSOR", "person_type": "employee", "document_id": "11144477735",
                       "enrollment_code": "9002", "site": "ESCOLA", "controller_user_id": "9002"})
    h = H.salvar_horario({"nome": "Turno manha", "dias": SEG_SEX})
    alunos = H.salvar_grupo({"nome": "Alunos", "site": "ESCOLA", "portas": [ent["id"]], "horario_id": h["id"]})
    profs = H.salvar_grupo({"nome": "Professores", "site": "ESCOLA", "portas": [ent["id"]]})
    S.set_group_members(alunos["id"], [a["id"]])
    S.set_group_members(profs["id"], [b["id"]])
    leitor = LeitorFalso({"9001": "ALUNO MANHA", "9002": "PROFESSOR", "7777": "SO NO LEITOR"})
    return ent, h, leitor


def test_horario_do_leitor_tem_4_faixas_e_feriado_e_do_local(banco):
    with pytest.raises(ValueError):
        H.salvar_horario({"nome": "X", "dias": {"1": [[f"{h:02d}:00", f"{h:02d}:30"] for h in range(5)]}})
    h = H.salvar_horario({"nome": "Y", "dias": {"1": [["08:00", "09:00"]], "feriado": [["08:00", "09:00"]]}})
    assert "feriado" not in h["dias"]
    f = H.salvar_feriados("ESCOLA", [{"data": "2026-10-12"}], {"modo": "faixas", "faixas": [["08:00", "12:00"]]})
    assert f["regra"] == {"modo": "faixas", "faixas": [["08:00", "12:00"]]}
    assert H.salvar_feriados("ESCOLA", [{"data": "2026-11-02"}])["regra"]["modo"] == "faixas"   # so a lista mudou
    with pytest.raises(ValueError):
        H.salvar_feriados("ESCOLA", [], {"modo": "faixas", "faixas": []})


def test_comparar_so_le_e_aloca_do_127_para_baixo(banco):
    ent, h, leitor = _cenario()
    r = E.comparar(get=leitor.get)
    assert leitor.escritas == []
    p = r["leitores"][0]
    assert p["horarios"] == [{"indice": 127, "chave": h["id"], "nome": "Turno manha", "estado": "novo"}]
    assert [(m["uid"], m["para"]) for m in p["pessoas_mudam"]] == [("9001", 127)]
    assert p["pessoas_iguais"] == 1 and p["mudancas"] == 2 and not p["erros"]


def test_enviar_grava_um_dia_por_vez_troca_so_quem_muda_e_le_de_volta(banco):
    ent, h, leitor = _cenario()
    r = E.enviar(ent["id"], "teste", get=leitor.get, post=leitor.post)
    assert r["ok"] and r["pessoas_trocadas"] == 1 and r["horarios_gravados"] == [{"indice": 127, "nome": "Turno manha"}]
    assert leitor.cfg["AccessTimeSchedule[127].TimeSchedule[1][0]"] == "1 06:30:00-12:30:00"
    assert leitor.cfg["AccessTimeSchedule[127].TimeSchedule[0][0]"] == "1 00:00:00-00:00:00"   # domingo fechado
    assert leitor.cfg["AccessTimeSchedule[127].Enable"] == "true"
    assert leitor.usuarios["9001"]["ts"] == [127] and leitor.usuarios["9002"]["ts"] == [0]
    assert leitor.usuarios["7777"]["ts"] == [0]                    # quem nao e do SightOps nao e tocado
    assert not any(k.startswith("AccessTimeSchedule[0].") for x in leitor.escritas if "UserList" not in x for k in x)
    # de novo: nada a fazer
    p = E.comparar(get=leitor.get)["leitores"][0]
    assert p["mudancas"] == 0 and p["horarios"][0]["estado"] == "igual"


def test_horario_que_sai_de_uso_volta_ao_padrao(banco):
    ent, h, leitor = _cenario()
    E.enviar(ent["id"], "teste", get=leitor.get, post=leitor.post)
    alunos = next(g for g in H.acesso()["grupos"] if g["nome"] == "Alunos")
    H.salvar_grupo({"id": alunos["id"], "nome": "Alunos", "site": "ESCOLA", "portas": [ent["id"]], "horario_id": ""})
    p = E.comparar(get=leitor.get)["leitores"][0]
    assert p["liberar"] == [127] and [(m["uid"], m["para"]) for m in p["pessoas_mudam"]] == [("9001", 0)]
    r = E.enviar(ent["id"], "teste", get=leitor.get, post=leitor.post)
    assert r["liberados"] == [127] and leitor.usuarios["9001"]["ts"] == [0]
    assert leitor.cfg["AccessTimeSchedule[127].Enable"] == "false"
    assert leitor.cfg["AccessTimeSchedule[127].TimeSchedule[3][0]"] == "1 00:00:00-23:59:59"


def test_indice_ocupado_pela_pagina_do_leitor_nao_e_usado(banco):
    ent, h, leitor = _cenario()
    leitor.cfg["AccessTimeSchedule[127].Enable"] = "true"           # feito por alguem na pagina web
    p = E.comparar(get=leitor.get)["leitores"][0]
    assert p["horarios"][0]["indice"] == 126


def test_horario_0_que_nao_e_24h_bloqueia_o_envio(banco):
    ent, h, leitor = _cenario()
    leitor.cfg["AccessTimeSchedule[0].TimeSchedule[0][0]"] = "1 08:00:00-18:00:00"
    p = E.comparar(get=leitor.get)["leitores"][0]
    assert p["erros"]
    with pytest.raises(Exception):
        E.enviar(ent["id"], "teste", get=leitor.get, post=leitor.post)
    assert leitor.escritas == []


def test_simulacao_usa_regra_de_feriado_do_local(banco):
    from datetime import datetime, timezone
    ent, h, leitor = _cenario()
    a = next(p for p in S.list_people() if p["controller_user_id"] == "9001")
    with db_store._conn() as c:
        c.execute("INSERT INTO access_events(id, tenant_slug, site, device_id, person_id, event_type, occurred_at) "
                  "VALUES('e1', 'escola-teste', 'ESCOLA', ?, ?, 'entrada', '2026-10-12 07:10:00')", (ent["id"], a["id"]))
    agora = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    H.salvar_feriados("ESCOLA", [{"data": "2026-10-12"}], {"modo": "fechado"})
    assert H.simular(dias=7, agora=agora)["barradas"] == 1
    H.salvar_feriados("ESCOLA", [{"data": "2026-10-12"}], {"modo": "normal"})
    assert H.simular(dias=7, agora=agora)["barradas"] == 0
    H.salvar_feriados("ESCOLA", [{"data": "2026-10-12"}], {"modo": "faixas", "faixas": [["09:00", "12:00"]]})
    assert H.simular(dias=7, agora=agora)["barradas"] == 1
