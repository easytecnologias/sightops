"""Notificacoes por site: quem recebe, juntar quedas, silencio, vincular pelo
robo da Easy e migracao da config antiga. So dados ficticios, sem Telegram."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core import tenant_context as T
from app.services import db_store
from app.services import notificacoes_service as N
from app.services import telegram_notification_service as TG


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(T, "DATA_DIR", tmp_path)
    db_store.init_db()
    enviados = []

    def falso(token, metodo, dados, timeout=20):
        enviados.append((token, metodo, dados))
        return {"ok": True, "result": {"username": "SightOpsAvisosBot"}}

    monkeypatch.setattr(N, "_telegram", falso)
    tok = T.set_current_tenant_slug("cliente-a")
    yield enviados
    T.reset_current_tenant_slug(tok)


def _grupo(**kw):
    base = {"nome": "G", "chat_id": "-1001", "bot": "easy", "ativo": True}
    base.update(kw)
    return N.salvar_grupo(base)


def test_quem_recebe(banco):
    N.salvar_bot_easy("123:abc", "https://sightops.exemplo.com.br/v2")
    padrao = _grupo(nome="NOC", chat_id="-1001", padrao=True)
    inco = _grupo(nome="Portaria", chat_id="-1002", sites=["incoforte"], eventos=["queda", "volta"], tipos=["camera"])
    tec = _grupo(nome="Tecnicos", chat_id="-1003", sites=["INCOFORTE", "JANGADEIROS"], eventos=["queda"])
    cfg = N.config()
    ids = lambda xs: sorted(g["nome"] for g in xs)
    assert ids(N.destinos(cfg, "Incoforte", "queda", "camera")) == ["Portaria", "Tecnicos"]
    assert ids(N.destinos(cfg, "INCOFORTE", "queda", "onu")) == ["Tecnicos"]          # Portaria so camera
    assert ids(N.destinos(cfg, "INCOFORTE", "sinal_onu", "onu")) == []                # ninguem do site quer; padrao NAO entra
    assert ids(N.destinos(cfg, "PERUCABA", "queda", "camera")) == ["NOC"]            # sem grupo proprio -> padrao
    assert ids(N.destinos(cfg, "", "panico")) == ["NOC"]
    assert padrao["id"] and inco["id"] and tec["id"]


def test_silencio_e_urgente(banco):
    _grupo(nome="Noite", padrao=True, silencio={"ativo": True, "de": "22:00", "ate": "06:00"})
    cfg = N.config()
    madrugada = datetime(2026, 10, 21, 5, 30, tzinfo=timezone.utc)   # 02:30 em Brasilia
    tarde = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)       # 15:00
    assert not N.destinos(cfg, "X", "queda", quando=madrugada)
    assert N.destinos(cfg, "X", "queda", urgente=True, quando=madrugada)
    assert N.destinos(cfg, "X", "queda", quando=tarde)
    with pytest.raises(ValueError):
        _grupo(nome="Ruim", silencio={"ativo": True, "de": "25:00", "ate": "06:00"})


def test_quedas_do_mesmo_site_viram_uma_mensagem(banco, monkeypatch):
    N.salvar_bot_easy("123:abc", "https://sightops.exemplo.com.br/v2")
    _grupo(nome="Portaria", chat_id="-1002", sites=["INCOFORTE"])
    entidades = [
        {"entity_type": "camera", "status": "down", "entity_key": f"camera:{i}", "display_name": f"CAM {i}",
         "site": "INCOFORTE", "ip": f"10.0.0.{i}", "detail_json": "{}"} for i in range(1, 4)
    ] + [{"entity_type": "camera", "status": "up", "entity_key": "camera:9", "display_name": "CAM 9", "site": "INCOFORTE", "detail_json": "{}"}]
    monkeypatch.setattr(TG, "list_entities", lambda limit=2000: [dict(e) for e in entidades])
    banco.clear()
    r = TG.process_monitoring_notifications()
    msgs = [d for (_, m, d) in banco if m == "sendMessage"]
    assert r["sent"] == 1 and len(msgs) == 1
    texto = msgs[0]["text"]
    assert "3 câmeras caíram" in texto and "INCOFORTE" in texto and "CAM 1 · 10.0.0.1" in texto
    assert msgs[0]["reply_markup"]["inline_keyboard"][0][0]["url"].startswith("https://sightops.exemplo.com.br/v2/?tela=")
    # segundo ciclo: nada novo
    banco.clear()
    TG.process_monitoring_notifications()
    assert not [1 for (_, m, _) in banco if m == "sendMessage"]
    # voltam: uma mensagem com o tempo fora
    for e in entidades:
        e["status"] = "up"
    banco.clear()
    TG.process_monitoring_notifications()
    msgs = [d for (_, m, d) in banco if m == "sendMessage"]
    assert len(msgs) == 1 and "3 câmeras voltaram" in msgs[0]["text"] and "fora" in msgs[0]["text"]


def test_site_inteiro_fura_o_silencio(banco, monkeypatch):
    N.salvar_bot_easy("123:abc")
    _grupo(nome="Noite", padrao=True, silencio={"ativo": True, "de": "00:00", "ate": "23:59"})
    entidades = [{"entity_type": "camera", "status": "down", "entity_key": f"c:{i}", "display_name": f"C{i}",
                  "site": "SUB", "detail_json": "{}"} for i in range(2)]
    monkeypatch.setattr(TG, "list_entities", lambda limit=2000: [dict(e) for e in entidades])
    monkeypatch.setattr(N, "_no_silencio", lambda g, quando=None: True)
    banco.clear()
    TG.process_monitoring_notifications()
    msgs = [d for (_, m, d) in banco if m == "sendMessage"]
    assert len(msgs) == 1 and "Site inteiro fora do ar" in msgs[0]["text"]


def test_silenciado_fica_pendente(banco, monkeypatch):
    N.salvar_bot_easy("123:abc")
    _grupo(nome="Noite", padrao=True)
    entidades = [{"entity_type": "camera", "status": "down", "entity_key": "c:1", "display_name": "C1", "site": "A", "detail_json": "{}"},
                 {"entity_type": "camera", "status": "up", "entity_key": "c:2", "display_name": "C2", "site": "A", "detail_json": "{}"}]
    monkeypatch.setattr(TG, "list_entities", lambda limit=2000: [dict(e) for e in entidades])
    monkeypatch.setattr(N, "_no_silencio", lambda g, quando=None: True)
    banco.clear()
    TG.process_monitoring_notifications()
    assert not [1 for (_, m, _) in banco if m == "sendMessage"]
    monkeypatch.setattr(N, "_no_silencio", lambda g, quando=None: False)  # amanheceu
    TG.process_monitoring_notifications()
    msgs = [d for (_, m, d) in banco if m == "sendMessage"]
    assert len(msgs) == 1 and "caiu" in msgs[0]["text"]


def test_vincular_so_no_cliente_do_codigo(banco):
    with pytest.raises(ValueError):
        N.novo_codigo("cliente-a")  # sem robo da Easy
    N.salvar_bot_easy("123:abc")
    c = N.novo_codigo("cliente-a")["codigo"]
    assert N.situacao_codigo("cliente-b", c)["status"] == "invalido"
    respostas = []
    tok = T.set_current_tenant_slug("cliente-b")  # o laco roda sem cliente; o codigo decide
    try:
        g = N.tratar_update({"update_id": 7, "message": {"text": f"/vincular@SightOpsAvisosBot {c.lower()}",
                                                         "chat": {"id": -100555, "title": "INCOFORTE Portaria"}}},
                            lambda chat, txt: respostas.append(txt))
    finally:
        T.reset_current_tenant_slug(tok)
    assert g and g["chat_id"] == "-100555" and g["padrao"] is True
    assert N.situacao_codigo("cliente-a", c)["status"] == "vinculado"
    assert [x["chat_id"] for x in N.config()["grupos"]] == ["-100555"]  # cliente-a
    tok = T.set_current_tenant_slug("cliente-b")
    try:
        assert N.config()["grupos"] == []
    finally:
        T.reset_current_tenant_slug(tok)
    # codigo usado nao vincula de novo
    assert N.tratar_update({"message": {"text": f"/vincular {c}", "chat": {"id": -1009}}}, lambda *a: None) is None


def test_migra_a_config_antiga(banco):
    s = db_store.load_app_settings()
    s["telegram_notifications"] = {"enabled": True, "bot_token": "999:x", "chat_id": "-1007", "notify_recovery": False,
                                   "warn_rx": -26, "critical_rx": -28}
    db_store.save_app_settings(s)
    cfg = N.config()
    g = cfg["grupos"][0]
    assert g["bot"] == "proprio" and g["padrao"] and g["chat_id"] == "-1007" and "volta" not in g["eventos"]
    assert cfg["bot_proprio_token"] == "999:x" and cfg["sinal"]["warn_rx"] == -26
    assert "999:x" not in str(N.config_publica())  # token nunca sai na resposta


def test_rotas_so_admin():
    from fastapi import FastAPI

    from app.core import security as SEC
    from app.core.settings import get_settings

    mw = SEC.ApiAuthMiddleware(FastAPI(), get_settings())
    for m in ("GET", "POST", "PUT", "DELETE"):
        assert mw._match_role_rule("/api/monitoring/notificacoes/grupos", m) == "admin"
