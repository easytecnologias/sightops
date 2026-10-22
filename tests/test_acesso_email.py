"""Aviso por e-mail com a foto da passagem: cadastro, fila, foto da gravacao,
envio, resumo, link publico e camera do local. SQLite temporario; SMTP e
gravador de mentira."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core import tenant_context
from app.services import access_control_email as AE
from app.services import access_control_store as S
from app.services import db_store

AGORA = datetime(2026, 10, 22, 13, 0, tzinfo=timezone.utc)          # 10:00 em Brasilia


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    monkeypatch.setattr(AE, "_RELOGIOS", {})
    token = tenant_context.set_current_tenant_slug("escola-teste")
    S.ensure_access_control_schema()
    yield tmp_path
    tenant_context.reset_current_tenant_slug(token)


@pytest.fixture()
def enviados(monkeypatch):
    caixa = []
    monkeypatch.setattr(AE, "_smtp_enviar", lambda cfg, para, assunto, texto, html, imagens=None, anexar=False:
                        caixa.append({"para": para, "assunto": assunto, "texto": texto, "html": html, "imagens": imagens or []}))
    return caixa


def _cenario(email="mae@exemplo.com.br", quando="passagem", foto="link"):
    leitor = S.save_device({"name": "ENTRADA - ESCOLA", "site": "ESCOLA", "vendor": "intelbras", "host": "192.168.1.201", "password": "x"})
    aluno = S.save_person({"full_name": "ALUNO TESTE", "person_type": "student", "class_name": "3º Ano", "enrollment_code": "900",
                           "document_id": "52998224725", "site": "ESCOLA", "controller_user_id": "900",
                           "guardian_name": "Maria", "guardian_email": email})
    AE.save_config({"site": "ESCOLA", "enabled": True, "host": "smtp.exemplo.com.br", "port": 587, "user": "avisos@exemplo.com.br",
                    "password": "segredo", "from_email": "avisos@exemplo.com.br", "from_name": "Escola", "quando": quando,
                    "foto": foto, "api_base": "https://sightops.exemplo.com.br/v3-api", "sem_foto_envia": True, "resumo_hora": "18:30"})
    return leitor, aluno


def _vincular(leitor, monkeypatch):
    cam = {"host": "10.0.0.5", "canal": 3, "http_port": 80, "connector_id": "", "titulo": "CAM 03 ENTRADA", "gravador": "NVR",
           "camera_ip": "", "status": "online", "fonte": "nvr"}
    monkeypatch.setattr(AE, "candidatas", lambda site: [cam] if site.upper() == "ESCOLA" else [])
    AE.salvar_cameras(leitor, ["10.0.0.5:3"])
    return cam


def _evento(leitor, aluno, quando="2026-10-22 09:59:00", tipo="entrada", eid="e1"):
    return {"id": eid, "event_type": tipo, "site": "ESCOLA", "person_id": aluno["id"], "device_id": leitor["id"], "occurred_at": quando}


def test_cadastro_nao_apaga_email_quando_o_pedido_nao_traz(banco):
    p = S.save_person({"full_name": "ALUNO", "person_type": "student", "enrollment_code": "1", "document_id": "52998224725",
                       "site": "ESCOLA", "guardian_email": "Mae@Exemplo.com.br "})
    assert p["guardian_email"] == "mae@exemplo.com.br"
    p = S.save_person({"id": p["id"], "full_name": "ALUNO NOVO NOME", "person_type": "student", "enrollment_code": "1",
                       "document_id": "52998224725", "site": "ESCOLA"})           # planilha / trazer do leitor
    assert p["guardian_email"] == "mae@exemplo.com.br" and p["email_enabled"] is True
    with pytest.raises(ValueError):
        S.save_person({"id": p["id"], "full_name": "X", "person_type": "student", "enrollment_code": "1",
                       "document_id": "52998224725", "site": "ESCOLA", "guardian_email": "nao-e-email"})


def test_fila_so_entra_o_que_deve(banco):
    leitor, aluno = _cenario()
    assert AE.enfileirar(_evento(leitor, aluno), agora=AGORA) == "email_queued"
    assert AE.enfileirar(_evento(leitor, aluno), agora=AGORA) == "email_queued"          # mesmo evento: uma linha so
    assert len(AE._rows("SELECT * FROM access_email_queue", ())) == 1
    fila = AE._rows("SELECT due_at FROM access_email_queue", ())[0]
    assert fila["due_at"] == "2026-10-22 13:02:00"                                     # 09:59 + 3 min, em UTC
    assert AE.enfileirar(_evento(leitor, aluno, "2026-10-22 09:00:00", eid="e2"), agora=AGORA) == "email_antigo"
    sem = S.save_person({"full_name": "SEM EMAIL", "person_type": "student", "enrollment_code": "2", "document_id": "11144477735",
                         "site": "ESCOLA"})
    assert AE.enfileirar({**_evento(leitor, aluno, eid="e3"), "person_id": sem["id"]}, agora=AGORA) == "email_skipped"
    AE.save_config({"site": "ESCOLA", "enabled": False, "host": "smtp.exemplo.com.br", "from_email": "a@exemplo.com.br"})
    assert AE.enfileirar(_evento(leitor, aluno, eid="e4"), agora=AGORA) == "email_skipped"


def test_envia_com_foto_da_gravacao_no_segundo_certo_e_link_que_vence(banco, enviados, monkeypatch):
    leitor, aluno = _cenario()
    cam = _vincular(leitor, monkeypatch)
    pedidos = []

    def capturar(c, momento, destino, largura=1280):
        pedidos.append(momento)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"\xff\xd8jpg" * 400)
    monkeypatch.setattr(AE, "capturar", capturar)
    AE.enfileirar(_evento(leitor, aluno), agora=AGORA)
    assert AE.processar_fila(agora=AGORA)["processados"] == 0                         # ainda nao venceu os 3 min
    AE.processar_fila(agora=AGORA + timedelta(minutes=3))
    assert pedidos == [datetime(2026, 10, 22, 9, 59)]
    assert len(enviados) == 1 and enviados[0]["para"] == "mae@exemplo.com.br"
    assert "ALUNO TESTE entrou" in enviados[0]["assunto"]
    linha = AE._rows("SELECT * FROM access_email_queue", ())[0]
    assert linha["status"] == "enviado" and linha["photo_token"] and "CAM" not in linha["error"]
    assert f"https://sightops.exemplo.com.br/v3-api/api/access-control/foto/{linha['photo_token']}" in enviados[0]["html"]
    assert enviados[0]["imagens"] == []                                               # link: a foto nao vai no e-mail
    assert AE.foto_publica(linha["photo_token"], agora=AGORA + timedelta(days=1))
    assert AE.foto_publica(linha["photo_token"], agora=AGORA + timedelta(days=8)) is None
    assert AE.foto_publica("x" * 30) is None
    AE.processar_fila(agora=AGORA + timedelta(days=8))                                 # limpeza tira a foto vencida
    assert not list((banco / "tenants" / "escola-teste" / AE.PASTA_FOTOS).glob("*.jpg"))


def test_gravador_sem_trecho_tenta_de_novo_e_depois_manda_sem_foto(banco, enviados, monkeypatch):
    leitor, aluno = _cenario()
    _vincular(leitor, monkeypatch)

    def falha(*a, **k):
        raise RuntimeError("sem gravacao nesse instante")
    monkeypatch.setattr(AE, "capturar", falha)
    AE.enfileirar(_evento(leitor, aluno), agora=AGORA)
    t = AGORA + timedelta(minutes=3)
    for _ in range(AE.TENTATIVAS):
        AE.processar_fila(agora=t)
        t += timedelta(minutes=AE.NOVA_TENTATIVA_MIN)
    assert enviados == []
    AE.processar_fila(agora=t)
    assert len(enviados) == 1 and "Sem imagem da câmera" in enviados[0]["html"]
    assert AE._rows("SELECT status FROM access_email_queue", ())[0]["status"] == "enviado"


def test_resumo_do_dia_junta_entrada_e_saida_no_horario(banco, enviados, monkeypatch):
    leitor, aluno = _cenario(quando="resumo", foto="anexo")
    _vincular(leitor, monkeypatch)
    monkeypatch.setattr(AE, "capturar", lambda c, m, d, largura=1280: (d.parent.mkdir(parents=True, exist_ok=True), d.write_bytes(b"\xff\xd8" * 900)))
    AE.enfileirar(_evento(leitor, aluno, "2026-10-22 09:59:00", "entrada", "e1"), agora=AGORA)
    AE.enfileirar(_evento(leitor, aluno, "2026-10-22 12:31:00", "saida", "e2"), agora=AGORA + timedelta(hours=2, minutes=32))
    AE.processar_fila(agora=AGORA + timedelta(hours=3))                               # 13:00: fotos prontas, sem envio
    assert enviados == []
    AE.processar_fila(agora=datetime(2026, 10, 22, 21, 31, tzinfo=timezone.utc))      # 18:31 local
    assert len(enviados) == 1 and len(enviados[0]["imagens"]) == 2
    assert "entradas e saídas" in enviados[0]["assunto"]


def test_camera_de_outro_local_e_recusada(banco, monkeypatch):
    leitor, _ = _cenario()
    monkeypatch.setattr(AE, "candidatas", lambda site: [{"host": "10.0.0.5", "canal": 3}] if site == "ESCOLA" else [])
    with pytest.raises(ValueError):
        AE.salvar_cameras(leitor, ["10.9.9.9:1"])
    outro = S.save_device({"name": "ENTRADA B", "site": "OUTRA", "vendor": "intelbras", "host": "192.168.9.1", "password": "x"})
    with pytest.raises(ValueError):
        AE.salvar_cameras(outro, ["10.0.0.5:3"])


def test_sugestao_pelo_nome_do_leitor():
    lista = [{"titulo": "CAM 01 QUADRA"}, {"titulo": "CAM 03 ENTRADA PORTAO"}, {"titulo": "CAM 07 SAIDA"}]
    assert AE.sugestao({"name": "ENTRADA - ESCOLA X", "site": "ESCOLA X"}, lista)["titulo"] == "CAM 03 ENTRADA PORTAO"


def test_link_da_foto_e_rota_publica_e_canal_de_email_e_de_admin():
    from app.core.settings import get_settings
    from app.core.security import ApiAuthMiddleware

    async def app_vazio(scope, receive, send):
        return None
    m = ApiAuthMiddleware(app_vazio, get_settings())
    assert m._is_public_path("/api/access-control/foto/abc") is True
    assert m._is_public_path("/api/access-control/email") is False
    assert m._regra_declarada("/api/access-control/email", "PUT") == "admin"
    assert m._regra_declarada("/api/access-control/email/test", "POST") == "admin"
    assert m._regra_declarada("/api/access-control/painel/cameras/x", "PUT") == "operator"
    assert m._regra_declarada("/api/access-control/painel/cameras/x/foto", "GET") == "operator"


def test_config_nao_devolve_senha_e_valida(banco):
    AE.save_config({"enabled": True, "host": "smtp.exemplo.com.br", "port": 465, "security": "ssl", "user": "a@exemplo.com.br",
                    "password": "segredo", "from_email": "a@exemplo.com.br"})
    c = AE.get_config("")
    assert c["password_saved"] is True and "password" not in c and c["security"] == "ssl"
    salvo = json.dumps(db_store.load_app_settings())
    assert "segredo" not in salvo                                                      # cifrada
    with pytest.raises(ValueError):
        AE.save_config({"host": "smtp bad host", "from_email": "a@exemplo.com.br"})


def test_historico_de_usuario_restrito_so_tem_os_locais_dele(banco):
    leitor, aluno = _cenario()
    AE.enfileirar(_evento(leitor, aluno), agora=AGORA)
    assert len(AE.historico("", locais=None)) == 1
    assert AE.historico("", locais=["OUTRA ESCOLA"]) == []
    assert len(AE.historico("", locais=["escola"])) == 1
    assert AE.historico("", locais=[]) == []
