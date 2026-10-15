"""Janela "Dados" do Painel de Acesso: backup so do cliente (ou do local) e
excluir um local inteiro com backup antes. SQLite temporario, leitores falsos
e pessoas ficticias."""
from __future__ import annotations

import json
import zipfile

import pytest
from fastapi import HTTPException

from app.core import tenant_context
from app.services import access_control_dados as D
from app.services import access_control_horarios as H
from app.services import access_control_store as S
from app.services import db_store


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug("condo-teste")
    S.ensure_access_control_schema()
    yield tmp_path
    tenant_context.reset_current_tenant_slug(token)


def _local(site, cpf, uid, ip):
    leitor = S.save_device({"name": f"ENTRADA {site}", "site": site, "vendor": "intelbras", "host": ip, "password": "x"})
    portas = S.save_door_group({"name": f"PORTAS {site}", "site": site})
    S.set_door_group_members(portas["id"], [leitor["id"]])
    grupo = S.save_group({"name": f"MORADORES {site}", "site": site})
    S.save_rule({"name": "24h", "people_group_id": grupo["id"], "door_group_id": portas["id"]})
    p = S.save_person({"full_name": f"MORADOR FICTICIO {site}", "person_type": "resident", "document_id": cpf,
                       "site": site, "controller_user_id": uid})
    S.set_group_members(grupo["id"], [p["id"]])
    S.upsert_provision_status(p["id"], leitor["id"], "ok")
    from app.services.access_control_photos import save_person_face_photo
    from PIL import Image
    import io
    b = io.BytesIO()
    Image.new("RGB", (40, 40), "green").save(b, "JPEG")
    save_person_face_photo(p["id"], b.getvalue())
    S.record_event({"site": site, "device_id": leitor["id"], "person_id": p["id"], "person_name_raw": p["full_name"],
                    "event_type": "access_granted", "occurred_at": "2026-10-15T10:00:00"})
    return {"leitor": leitor, "portas": portas, "grupo": grupo, "pessoa": p}


def _cenario():
    return _local("RESERVA", "52998224725", "7001", "10.10.9.10"), _local("JARDINS", "11144477735", "7002", "10.10.10.10")


def test_backup_do_local_so_leva_o_local_e_as_fotos(banco):
    reserva, jardins = _cenario()
    r = D.fazer_backup("reserva", "admin")
    with zipfile.ZipFile(D.arquivo_backup(r["nome"])) as z:
        pessoas = json.loads(z.read("tabelas/access_people.json"))
        regras = json.loads(z.read("tabelas/access_rules.json"))
        nomes = z.namelist()
        m = json.loads(z.read("manifesto.json"))
    assert [p["id"] for p in pessoas] == [reserva["pessoa"]["id"]]
    assert [x["people_group_id"] for x in regras] == [reserva["grupo"]["id"]]
    assert f"fotos/access-control/faces/{reserva['pessoa']['id']}.jpg" in nomes
    assert not any(jardins["pessoa"]["id"] in n for n in nomes)
    assert m["cliente"] == "condo-teste" and m["site"] == "reserva" and m["contagem"]["fotos"] == 1
    assert r["nome"].startswith("acesso-reserva-")


def test_backup_nao_leva_outro_cliente(banco):
    _cenario()
    token = tenant_context.set_current_tenant_slug("outro-cliente")
    try:
        r = D.fazer_backup("", "admin")
        assert r["contagem"]["access_people"] == 0 and r["contagem"]["fotos"] == 0
        assert D.resumo()["locais"] == []
    finally:
        tenant_context.reset_current_tenant_slug(token)


def test_baixar_recusa_nome_inventado(banco):
    for nome in ("../teste.db", "acesso-x-20261015-1200.zip", "acesso-cliente-20261015-120000.zip"):
        with pytest.raises(HTTPException) as e:
            D.arquivo_backup(nome)
        assert e.value.status_code in (400, 404)


def test_excluir_local_pede_o_nome_e_nao_apaga_nada_sem_ele(banco):
    reserva, _ = _cenario()
    with pytest.raises(HTTPException) as e:
        D.excluir_local("RESERVA", "reserv", usuario="admin", remover=lambda d, u: None)
    assert e.value.status_code == 400
    assert len(S.list_people()) == 2 and D.backups() == []


def test_excluir_local_faz_backup_tira_do_leitor_e_apaga_so_o_local(banco):
    reserva, jardins = _cenario()
    H.salvar_feriados("RESERVA", [{"data": "2026-12-25", "nome": "Natal"}])
    chamadas = []
    r = D.excluir_local("RESERVA", " reserva ", usuario="admin", remover=lambda d, uid: chamadas.append((d["name"], uid)))
    assert r["ok"] and r["pessoas_excluidas"] == 1 and r["leitores"] == 1 and r["grupos"] == 1 and r["grupos_portas"] == 1
    assert chamadas == [("ENTRADA RESERVA", "7001")]            # saiu do leitor antes de sair do SightOps
    assert [p["id"] for p in S.list_people()] == [jardins["pessoa"]["id"]]
    assert [d["id"] for d in S.list_devices()] == [jardins["leitor"]["id"]]
    assert [g["id"] for g in S.list_groups()] == [jardins["grupo"]["id"]]
    assert [x["people_group_id"] for x in S.list_rules()] == [jardins["grupo"]["id"]]
    assert not (banco / "tenants/condo-teste/access-control/faces" / f"{reserva['pessoa']['id']}.jpg").exists()
    assert (banco / "tenants/condo-teste/access-control/faces" / f"{jardins['pessoa']['id']}.jpg").exists()
    assert "RESERVA" not in H._ler()["feriados"]
    assert r["passagens"] == 0 and D.coletar("RESERVA")["access_events"]   # historico fica, salvo se pedirem
    b = D.backups()[0]
    assert b["nome"] == r["backup"] and b["motivo"] == "antes de excluir o local" and b["contagem"]["access_people"] == 1


def test_excluir_local_com_historico(banco):
    _cenario()
    r = D.excluir_local("RESERVA", "RESERVA", apagar_historico=True, usuario="admin", remover=lambda d, u: None)
    assert r["passagens"] == 1 and D.coletar("RESERVA")["access_events"] == []
    assert len(D.coletar("JARDINS")["access_events"]) == 1


def test_leitor_fora_do_ar_para_a_exclusao_e_nao_apaga_leitor_nem_grupo(banco):
    reserva, _ = _cenario()

    def falha(device, uid):
        raise HTTPException(status_code=502, detail="timeout")

    r = D.excluir_local("RESERVA", "RESERVA", usuario="admin", remover=falha)
    assert r["ok"] is False and r["pessoas_excluidas"] == 0 and r["pessoas_mantidas"][0]["falhas"][0]["erro"] == "timeout"
    assert r["leitores"] == 0 and r["grupos"] == 0
    assert any(d["id"] == reserva["leitor"]["id"] for d in S.list_devices())
    assert not next(p for p in S.list_people() if p["id"] == reserva["pessoa"]["id"])["active"]
    assert r["backup"]                                            # o backup foi feito antes de tentar


def test_rotas_de_dados_exigem_admin():
    from app.core.security import ApiAuthMiddleware
    from app.core.settings import get_settings

    async def app_vazio(scope, receive, send):
        return None

    regras = ApiAuthMiddleware(app_vazio, get_settings())
    assert regras._match_role_rule("/api/access-control/painel/dados", "GET") == "admin"
    assert regras._match_role_rule("/api/access-control/painel/dados/backup/acesso-cliente-20261015-120000.zip", "GET") == "admin"
    assert regras._match_role_rule("/api/access-control/painel/dados/excluir-local", "POST") == "admin"
    assert regras._match_role_rule("/api/access-control/painel/dados/backup", "POST") == "admin"


def test_foto_fora_da_pasta_do_cliente_nao_entra_nem_e_apagada(banco):
    reserva, _ = _cenario()
    vizinho = banco / "tenants/condo-teste2/access-control/faces/x.jpg"
    vizinho.parent.mkdir(parents=True)
    vizinho.write_bytes(b"foto do vizinho")
    with db_store._conn() as c:
        c.execute("UPDATE access_people SET face_photo_path=? WHERE id=?",
                  ("access-control/faces/../../../condo-teste2/access-control/faces/x.jpg", reserva["pessoa"]["id"]))
    assert D.fazer_backup("RESERVA")["contagem"]["fotos"] == 0
    D.excluir_local("RESERVA", "RESERVA", remover=lambda d, u: None)
    assert vizinho.read_bytes() == b"foto do vizinho"


def test_foto_com_id_que_sobe_pasta_e_recusada(banco):
    from app.services.access_control_photos import save_person_face_photo
    with pytest.raises(ValueError):
        save_person_face_photo("../../outro/access-control/faces/abc", b"x")


def test_exclusao_em_segundo_plano_mostra_andamento_e_so_para_o_cliente(banco, monkeypatch):
    import time
    from app.services import access_control_pessoas as P
    _cenario()
    monkeypatch.setattr(P, "_remover_do_leitor", lambda d, u: None)
    t = D.iniciar_exclusao("RESERVA", "RESERVA", usuario="admin")
    assert t["estado"] == "rodando" and t["total"] == 1 and "cliente" not in t
    for _ in range(200):
        r = D.ver_exclusao(t["id"])
        if r["estado"] != "rodando":
            break
        time.sleep(0.05)
    assert r["estado"] == "pronto" and r["resultado"]["pessoas_excluidas"] == 1
    token = tenant_context.set_current_tenant_slug("outro-cliente")
    try:
        with pytest.raises(HTTPException):
            D.ver_exclusao(t["id"])
    finally:
        tenant_context.reset_current_tenant_slug(token)


def test_exclusao_em_segundo_plano_recusa_nome_errado_na_hora(banco):
    _cenario()
    with pytest.raises(HTTPException) as e:
        D.iniciar_exclusao("RESERVA", "JARDINS")
    assert e.value.status_code == 400
