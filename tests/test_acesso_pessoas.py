"""Aba Pessoas: excluir tira dos leitores antes de apagar, grupos de uma pessoa
so mexem nela e quem sai do grupo sai do leitor. SQLite temporario e leitores
falsos: nenhum equipamento e nenhuma pessoa real."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import tenant_context
from app.services import access_control_store as S
from app.services import db_store


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
    """Duas portas (ENTRADA, SAIDA) em dois grupos de porta; grupo ALUNOS abre a
    ENTRADA, grupo FUNCIONARIOS abre as duas. Pessoa ficticia no grupo ALUNOS."""
    ent = S.save_device({"name": "ENTRADA", "site": "ESCOLA", "vendor": "intelbras", "host": "192.168.1.201", "password": "x"})
    sai = S.save_device({"name": "SAIDA", "site": "ESCOLA", "vendor": "intelbras", "host": "192.168.1.202", "password": "x"})
    pg_ent = S.save_door_group({"name": "PORTA ENTRADA", "site": "ESCOLA"})
    S.set_door_group_members(pg_ent["id"], [ent["id"]])
    pg_todas = S.save_door_group({"name": "TODAS", "site": "ESCOLA"})
    S.set_door_group_members(pg_todas["id"], [ent["id"], sai["id"]])
    alunos = S.save_group({"name": "ALUNOS", "site": "ESCOLA"})
    func = S.save_group({"name": "FUNCIONARIOS", "site": "ESCOLA"})
    S.save_rule({"name": "r1", "people_group_id": alunos["id"], "door_group_id": pg_ent["id"]})
    S.save_rule({"name": "r2", "people_group_id": func["id"], "door_group_id": pg_todas["id"]})
    p = S.save_person({"full_name": "PESSOA FICTICIA", "person_type": "student", "document_id": "52998224725",
                       "enrollment_code": "9001", "site": "ESCOLA", "controller_user_id": "9001"})
    S.set_group_members(alunos["id"], [p["id"]])
    S.upsert_provision_status(p["id"], ent["id"], "ok")
    return {"ent": ent, "sai": sai, "alunos": alunos, "func": func, "pessoa": p}


def test_excluir_tira_do_leitor_pelo_id_da_controladora_e_apaga(banco):
    from app.services.access_control_pessoas import excluir
    c = _cenario()
    chamadas = []
    r = excluir(c["pessoa"]["id"], remover=lambda device, uid: chamadas.append((device["name"], uid)))
    assert r["excluida"] is True and r["removidos"] == ["ENTRADA"]
    assert chamadas == [("ENTRADA", "9001")]          # ID da controladora, nao o uuid
    assert not any(p["id"] == c["pessoa"]["id"] for p in S.list_people())
    assert S.list_provision_status_for_person(c["pessoa"]["id"]) == []
    assert c["pessoa"]["id"] not in S.list_group_members(c["alunos"]["id"])


def test_excluir_com_leitor_fora_do_ar_desativa_e_nao_apaga(banco):
    from app.services.access_control_pessoas import excluir
    c = _cenario()

    def falha(device, uid):
        raise HTTPException(status_code=502, detail="Nao foi possivel remover no dispositivo: timeout")

    r = excluir(c["pessoa"]["id"], remover=falha)
    assert r["excluida"] is False and r["desativada"] is True
    assert r["falhas"][0]["leitor"] == "ENTRADA" and "timeout" in r["falhas"][0]["erro"]
    pessoa = next(p for p in S.list_people() if p["id"] == c["pessoa"]["id"])
    assert not pessoa["active"]                        # vai congelada (UserStatus 1) quando o leitor voltar
    assert [x["status"] for x in S.list_provision_status_for_person(c["pessoa"]["id"])] == ["pending"]


def test_grupos_de_uma_pessoa_nao_mexem_nos_outros_membros(banco):
    from app.services.access_control_pessoas import definir_grupos
    c = _cenario()
    outra = S.save_person({"full_name": "OUTRA FICTICIA", "person_type": "employee", "document_id": "11144477735",
                           "site": "ESCOLA", "controller_user_id": "9002"})
    S.set_group_members(c["func"]["id"], [outra["id"]])
    r = definir_grupos(c["pessoa"]["id"], [c["alunos"]["id"], c["func"]["id"]], remover=lambda d, u: None)
    assert r["entrou"] == [c["func"]["id"]] and r["saiu"] == []
    assert set(S.list_group_members(c["func"]["id"])) == {outra["id"], c["pessoa"]["id"]}
    # entrou em FUNCIONARIOS: SAIDA passa a valer e fica pendente para o envio
    st = {x["device_id"]: x["status"] for x in S.list_provision_status_for_person(c["pessoa"]["id"])}
    assert st[c["sai"]["id"]] == "pending"


def test_quem_sai_do_grupo_sai_do_leitor_e_nao_volta_pelo_reenvio(banco):
    from app.services.access_control_pessoas import definir_grupos
    c = _cenario()
    definir_grupos(c["pessoa"]["id"], [c["alunos"]["id"], c["func"]["id"]], remover=lambda d, u: None)
    S.upsert_provision_status(c["pessoa"]["id"], c["sai"]["id"], "ok")
    removidos = []
    r = definir_grupos(c["pessoa"]["id"], [c["alunos"]["id"]], remover=lambda d, u: removidos.append((d["name"], u)))
    assert removidos == [("SAIDA", "9001")] and r["removidos"] == ["SAIDA"]
    st = {x["device_id"] for x in S.list_provision_status_for_person(c["pessoa"]["id"])}
    assert c["sai"]["id"] not in st                    # sem linha, o reenvio nao recadastra


def test_grupo_de_outro_cliente_e_recusado(banco):
    from app.services.access_control_pessoas import definir_grupos
    c = _cenario()
    with pytest.raises(HTTPException) as e:
        definir_grupos(c["pessoa"]["id"], ["grupo-que-nao-e-daqui"])
    assert e.value.status_code == 400


def test_lista_traz_grupos_leitores_e_situacao(banco, monkeypatch):
    from app.services import access_control_painel as Painel
    from app.services.access_control_pessoas import pessoas
    monkeypatch.setattr(Painel, "_locais_do_cliente", lambda: [])
    c = _cenario()
    r = pessoas()
    p = r["pessoas"][0]
    assert p["nome"] == "PESSOA FICTICIA" and p["grupos"] == [c["alunos"]["id"]]
    assert p["leitores"][0]["leitor"] == "ENTRADA" and p["leitores"][0]["status"] == "ok"
    grupos = {g["nome"]: g for g in r["grupos"]}
    assert [x["nome"] for x in grupos["FUNCIONARIOS"]["leitores"]] == ["ENTRADA", "SAIDA"]
    assert grupos["ALUNOS"]["membros"] == 1


def test_trazer_do_leitor_sem_cpf_com_foto_sem_grupo_e_sem_duplicar(banco, monkeypatch):
    import io
    from PIL import Image
    from app.services import access_control_import as Imp
    from app.services.access_control_pessoas import trazer_do_leitor
    monkeypatch.setattr(Imp, "_tipo_do_local", lambda site: "condominio")
    leitor = S.save_device({"name": "ACADEMIA", "site": "RESERVA", "vendor": "intelbras", "host": "10.0.0.1", "password": "x"})
    b = io.BytesIO(); Image.new("RGB", (30, 30), "blue").save(b, "JPEG")
    no_leitor = [{"controller_user_id": "1004", "full_name": "ADRIZIA.jpg I 29", "raw_active": "0"},
                 {"controller_user_id": "570", "full_name": "MARIA FICTICIA F13", "raw_active": "0"},
                 {"controller_user_id": "", "full_name": "SEM ID", "raw_active": "0"}]
    fotos = {"1004": b.getvalue(), "570": None}
    r = trazer_do_leitor(leitor["id"], listar=lambda d: no_leitor, baixar_foto=lambda d, uid: fotos[uid])
    assert r["criadas"] == 2 and r["fotos"] == 1 and [x["id"] for x in r["sem_foto"]] == ["570"] and len(r["recusadas"]) == 1
    pessoas = {p["controller_user_id"]: p for p in S.list_people()}
    assert pessoas["1004"]["full_name"] == "ADRIZIA I 29" and pessoas["1004"]["document_id"] == ""
    assert pessoas["1004"]["person_type"] == "resident" and pessoas["1004"]["site"] == "RESERVA"
    assert pessoas["1004"]["face_photo_path"] and not pessoas["570"]["face_photo_path"]
    assert S.list_provision_status_for_person(pessoas["1004"]["id"]) == []      # nada vai ao leitor
    # de novo: ninguem duplica (sem CPF, o ID no leitor e a identidade)
    r2 = trazer_do_leitor(leitor["id"], listar=lambda d: no_leitor, baixar_foto=lambda d, uid: fotos[uid])
    assert r2["criadas"] == 0 and r2["ja_existiam"] == 2 and len(S.list_people()) == 2


def test_sem_cpf_so_com_id_no_leitor_e_id_nao_se_repete(banco, monkeypatch):
    monkeypatch.setattr(S, "cpf_opcional", lambda site: False)          # local que nao e condominio
    with pytest.raises(ValueError):
        S.save_person({"full_name": "SEM NADA", "person_type": "resident", "site": "X"})
    S.save_person({"full_name": "A", "person_type": "resident", "site": "X", "controller_user_id": "77"})
    with pytest.raises(ValueError):
        S.save_person({"full_name": "B", "person_type": "resident", "site": "X", "controller_user_id": "77"})


def test_cpf_por_tipo_de_local(banco, monkeypatch):
    """Condominio: CPF opcional e o SightOps gera o ID no leitor (proximo livre).
    Escola, empresa e evento: CPF obrigatorio."""
    from app.services import access_control_painel as Painel
    tipos = {"RESERVA": "condominio", "ESCOLA": "escola", "FIRMA": "empresa", "SHOW": "evento"}
    monkeypatch.setattr(Painel, "_perfil", lambda site: {"tipo": tipos.get(site, "")})
    S.save_person({"full_name": "MORADOR DO LEITOR", "person_type": "resident", "site": "RESERVA", "controller_user_id": "5007"})
    a = S.save_person({"full_name": "MORADOR NOVO A01", "person_type": "resident", "site": "RESERVA"})
    b = S.save_person({"full_name": "OUTRO MORADOR A02", "person_type": "resident", "site": "RESERVA"})
    assert a["document_id"] == "" and a["controller_user_id"] == "5008" and b["controller_user_id"] == "5009"
    for site in ("ESCOLA", "FIRMA", "SHOW"):
        with pytest.raises(ValueError, match="CPF"):
            S.save_person({"full_name": "SEM CPF", "person_type": "employee", "site": site})
