"""LGPD (frente L do backlog): link da foto do e-mail (24 h, abertura no
historico, foto desligavel) e eliminacao dos dados de pessoa excluida.
SQLite temporario, pessoas ficticias; nada de equipamento."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core import tenant_context
from app.services import access_control_email as AE
from app.services import access_control_store as S
from app.services import auth_store as A
from app.services import db_store
from app.services import historico_service as H

AGORA = datetime(2026, 10, 22, 13, 0, tzinfo=timezone.utc)          # 10:00 em Brasilia


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    monkeypatch.setattr(AE, "_RELOGIOS", {})
    monkeypatch.setenv("AUTH_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("AUTH_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("AUTH_DEFAULT_ADMIN_USERNAME", "dono-teste")
    monkeypatch.setenv("AUTH_DEFAULT_ADMIN_PASSWORD", "dono-teste-123")
    monkeypatch.setattr(A, "_SCHEMA_READY", False)
    A.init_auth_db()
    dono = A.authenticate_user("dono-teste", "dono-teste-123")
    A.create_tenant(dono, slug="escola-teste", name="Escola Teste", owner_username="dono-e", owner_password="senha-teste-123")
    A.create_tenant(dono, slug="outra-escola", name="Outra", owner_username="dono-o", owner_password="senha-teste-123")
    token = tenant_context.set_current_tenant_slug("escola-teste")
    S.ensure_access_control_schema()
    yield {"dir": tmp_path, "dono": A.authenticate_user("dono-e", "senha-teste-123"),
           "outro": A.authenticate_user("dono-o", "senha-teste-123")}
    tenant_context.reset_current_tenant_slug(token)


@pytest.fixture()
def enviados(monkeypatch):
    caixa = []
    monkeypatch.setattr(AE, "_smtp_enviar", lambda cfg, para, assunto, texto, html, imagens=None, anexar=False:
                        caixa.append({"para": para, "assunto": assunto, "texto": texto, "html": html, "imagens": imagens or []}))
    return caixa


def _cenario(monkeypatch, foto="link"):
    leitor = S.save_device({"name": "ENTRADA - ESCOLA", "site": "ESCOLA", "vendor": "intelbras", "host": "192.168.1.201", "password": "x"})
    aluno = S.save_person({"full_name": "ALUNO FICTICIO", "person_type": "student", "enrollment_code": "900",
                           "document_id": "52998224725", "site": "ESCOLA", "controller_user_id": "900",
                           "guardian_name": "Maria", "guardian_email": "mae@exemplo.com.br"})
    AE.save_config({"site": "ESCOLA", "enabled": True, "host": "smtp.exemplo.com.br", "port": 587, "user": "avisos@exemplo.com.br",
                    "password": "segredo", "from_email": "avisos@exemplo.com.br", "quando": "passagem", "foto": foto,
                    "api_base": "https://sightops.exemplo.com.br/v3-api", "sem_foto_envia": True})
    cam = {"host": "10.0.0.5", "canal": 3, "http_port": 80, "connector_id": "", "titulo": "CAM 03", "gravador": "NVR",
           "camera_ip": "", "status": "online", "fonte": "nvr"}
    monkeypatch.setattr(AE, "candidatas", lambda site: [cam])
    AE.salvar_cameras(leitor, ["10.0.0.5:3"])
    pedidos = []

    def capturar(c, momento, destino, largura=1280):
        pedidos.append(momento)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"\xff\xd8jpg" * 400)
    monkeypatch.setattr(AE, "capturar", capturar)
    evento = {"id": "e1", "event_type": "entrada", "site": "ESCOLA", "person_id": aluno["id"], "device_id": leitor["id"],
              "occurred_at": "2026-10-22 09:59:00"}
    return leitor, aluno, evento, pedidos


def _lgpd(user, acao):
    return [e for e in H.consultar(user, tipo="lgpd")["eventos"] if e["action"] == acao]


# ------------------------------------------------------------------ L1

def test_link_da_foto_vale_24h_e_cada_abertura_vai_ao_historico(banco, enviados, monkeypatch):
    _, _, evento, _ = _cenario(monkeypatch)
    AE.enfileirar(evento, agora=AGORA)
    AE.processar_fila(agora=AGORA + timedelta(minutes=3))
    linha = AE._rows("SELECT * FROM access_email_queue", ())[0]
    assert linha["status"] == "enviado" and linha["photo_token"]
    assert "24 horas" in enviados[0]["html"] and "7 dias" not in enviados[0]["html"]
    tk = linha["photo_token"]
    assert AE.foto_publica(tk, agora=AGORA + timedelta(hours=23), ip="200.1.2.3")
    assert AE.foto_publica(tk, agora=AGORA + timedelta(hours=23, minutes=1), ip="200.1.2.4")
    assert AE.foto_publica(tk, agora=AGORA + timedelta(hours=25)) is None        # venceu: nao abre nem registra
    aberturas = _lgpd(banco["dono"], "lgpd.foto_aberta")
    assert len(aberturas) == 2
    d = json.loads(aberturas[0]["detail_json"])
    assert d["foto"] == linha["id"] and d["ip"] in ("200.1.2.3", "200.1.2.4") and aberturas[0]["resource_id"] == linha["id"]
    assert not _lgpd(banco["outro"], "lgpd.foto_aberta")                         # outro cliente nao ve


def test_validade_do_link_vem_do_ambiente(monkeypatch):
    monkeypatch.setenv("ACCESS_EMAIL_LINK_HORAS", "6")
    assert AE._link_horas() == 6
    monkeypatch.setenv("ACCESS_EMAIL_LINK_HORAS", "9999")
    assert AE._link_horas() == 168
    monkeypatch.setenv("ACCESS_EMAIL_LINK_HORAS", "abc")
    assert AE._link_horas() == 24
    monkeypatch.delenv("ACCESS_EMAIL_LINK_HORAS")
    assert AE._link_horas() == 24


def test_padrao_continua_link_e_cliente_pode_desligar_a_foto(banco, enviados, monkeypatch):
    assert AE.config_efetiva("ESCOLA")["foto"] == "link"                          # quem ja tem nao muda
    _, _, evento, pedidos = _cenario(monkeypatch, foto="nenhuma")
    assert AE.get_config("ESCOLA")["foto"] == "nenhuma"
    AE.enfileirar(evento, agora=AGORA)
    AE.processar_fila(agora=AGORA + timedelta(minutes=3))
    linha = AE._rows("SELECT * FROM access_email_queue", ())[0]
    assert pedidos == []                                                          # nem pede foto ao gravador
    assert linha["status"] == "enviado" and not linha["photo_token"] and not linha["photo_file"]
    assert len(enviados) == 1 and enviados[0]["imagens"] == []
    assert "/foto/" not in enviados[0]["html"] and "Sem imagem" not in enviados[0]["html"]
    with pytest.raises(ValueError):
        AE.save_config({"site": "ESCOLA", "foto": "qualquer"})


# ------------------------------------------------------------------ L2

def _foto_jpg() -> bytes:
    from io import BytesIO

    from PIL import Image
    out = BytesIO()
    Image.new("RGB", (40, 50), (120, 90, 60)).save(out, format="JPEG")
    return out.getvalue()


def _passagem(leitor, pessoa, eid):
    return S.record_event({
        "site": "ESCOLA", "device_id": leitor["id"], "device_name": "ENTRADA", "person_id": pessoa["id"],
        "person_name_raw": pessoa["full_name"], "event_type": "entrada", "raw_event_id": eid,
        "raw_payload": json.dumps({"UserName": pessoa["full_name"], "CardNo": "52998224725", "method": "15", "foto": "base64..."}),
        "occurred_at": f"2026-10-22 {7 + int(eid[-1]):02d}:00:00",   # 1 h entre elas (o leitor junta 5 min)
    })


def test_excluir_pessoa_apaga_foto_anonimiza_passagens_e_registra(banco, enviados, monkeypatch):
    from app.services.access_control_photos import save_person_face_photo
    leitor, aluno, evento, _ = _cenario(monkeypatch)
    outra = S.save_person({"full_name": "OUTRA FICTICIA", "person_type": "student", "enrollment_code": "901",
                           "document_id": "11144477735", "site": "ESCOLA"})
    face = save_person_face_photo(aluno["id"], _foto_jpg())
    arq_face = banco["dir"] / "tenants" / "escola-teste" / face["face_photo_path"]
    assert arq_face.exists()
    _passagem(leitor, aluno, "r1")
    _passagem(leitor, aluno, "r2")
    _passagem(leitor, outra, "r3")
    AE.enfileirar(evento, agora=AGORA)
    AE.processar_fila(agora=AGORA + timedelta(minutes=3))
    foto_email = AE._rows("SELECT photo_file FROM access_email_queue", ())[0]["photo_file"]
    assert (AE._pasta_fotos() / foto_email).exists()

    assert S.delete_person(aluno["id"]) is True

    assert not arq_face.exists()
    assert not (AE._pasta_fotos() / foto_email).exists()
    ev = AE._rows("SELECT person_id, person_name_raw, raw_payload FROM access_events WHERE tenant_slug=? ORDER BY raw_event_id",
                  ("escola-teste",))
    assert [e["person_name_raw"] for e in ev] == ["Pessoa excluída", "Pessoa excluída", "OUTRA FICTICIA"]
    assert ev[0]["person_id"] == aluno["id"]                                      # pseudonimo: a contagem continua
    for e in ev[:2]:
        assert "ALUNO" not in e["raw_payload"] and "52998224725" not in e["raw_payload"] and "base64" not in e["raw_payload"]
    assert "OUTRA FICTICIA" in ev[2]["raw_payload"]                               # quem nao foi excluido fica igual
    fila = AE._rows("SELECT photo_file, photo_token, email FROM access_email_queue", ())[0]
    assert fila == {"photo_file": "", "photo_token": "", "email": ""}
    elim = _lgpd(banco["dono"], "lgpd.eliminacao")
    assert len(elim) == 1 and elim[0]["resource_id"] == aluno["id"]
    d = json.loads(elim[0]["detail_json"])
    assert d["fotos_apagadas"] == 2 and d["passagens_anonimizadas"] == 2 and "ALUNO" not in elim[0]["detail_json"]
    assert not _lgpd(banco["outro"], "lgpd.eliminacao")
    assert S.delete_person(aluno["id"]) is False                                  # ja apagada: nada a registrar
    assert len(_lgpd(banco["dono"], "lgpd.eliminacao")) == 1


def test_eliminacao_nao_alcanca_outro_cliente(banco):
    from app.services.access_control_photos import save_person_face_photo
    leitor = S.save_device({"name": "ENTRADA - ESCOLA", "site": "ESCOLA", "vendor": "intelbras", "host": "192.168.1.201", "password": "x"})
    aqui = S.save_person({"full_name": "ALUNO AQUI", "person_type": "student", "enrollment_code": "1", "document_id": "52998224725",
                          "site": "ESCOLA"})
    _passagem(leitor, aqui, "a1")
    tk = tenant_context.set_current_tenant_slug("outra-escola")
    try:
        S.ensure_access_control_schema()
        leitor_o = S.save_device({"name": "ENTRADA - X", "site": "X", "vendor": "intelbras", "host": "192.168.1.202", "password": "x"})
        la = S.save_person({"full_name": "ALUNO LA", "person_type": "student", "enrollment_code": "1", "document_id": "52998224725",
                            "site": "X"})
        save_person_face_photo(la["id"], _foto_jpg())
        _passagem(leitor_o, la, "b1")
    finally:
        tenant_context.reset_current_tenant_slug(tk)
    assert S.delete_person(la["id"]) is False                                     # id do outro cliente: nada acontece
    assert (banco["dir"] / "tenants" / "outra-escola" / "access-control" / "faces" / f"{la['id']}.jpg").exists()
    nomes = {r["person_name_raw"] for r in AE._rows("SELECT person_name_raw FROM access_events", ())}
    assert nomes == {"ALUNO AQUI", "ALUNO LA"}

