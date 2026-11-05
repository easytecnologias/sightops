"""A6: aviso para varios grupos -- um entregue marcava todos.

Agora quem recebeu nao recebe de novo e so o grupo que falhou e tentado de
novo. SQLite temporario e Telegram falso."""
from __future__ import annotations

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
    estado = {"cai": set(), "enviados": []}

    def falso(token, metodo, dados, timeout=20):
        if metodo == "sendMessage":
            if dados["chat_id"] in estado["cai"]:
                return {"ok": False, "description": "Bad Request: chat not found"}
            estado["enviados"].append((dados["chat_id"], dados["text"]))
        return {"ok": True, "result": {}}

    monkeypatch.setattr(N, "_telegram", falso)
    tok = T.set_current_tenant_slug("cliente-a")
    yield estado
    T.reset_current_tenant_slug(tok)


def _grupo(**kw):
    base = {"nome": "G", "chat_id": "-1001", "bot": "easy", "ativo": True}
    base.update(kw)
    g = N.salvar_grupo(base)
    cfg = N.config()
    cfg.pop("base_pendente", None)
    N._salvar(cfg)
    return g


def test_so_o_grupo_que_falhou_recebe_de_novo(banco, monkeypatch):
    N.salvar_bot_easy("123:abc")
    _grupo(nome="Portaria", chat_id="-1002", sites=["SITE A"])
    _grupo(nome="Tecnicos", chat_id="-1003", sites=["SITE A"])
    entidades = [{"entity_type": "camera", "status": "down", "entity_key": "cam:1", "display_name": "CAM 1",
                  "site": "SITE A", "detail_json": "{}"}]
    monkeypatch.setattr(TG, "list_entities_todas", lambda **k: ([dict(e) for e in entidades], False))

    banco["cai"] = {"-1003"}
    r = TG.process_monitoring_notifications()
    assert [c for c, _ in banco["enviados"]] == ["-1002"]
    assert r["grupos_pendentes"] == 1

    # proximo ciclo, Tecnicos ainda fora: Portaria NAO recebe de novo
    banco["enviados"].clear()
    TG.process_monitoring_notifications()
    assert banco["enviados"] == []

    # Tecnicos voltou: recebe a queda, so ele, uma vez
    banco["cai"] = set()
    r = TG.process_monitoring_notifications()
    assert [c for c, _ in banco["enviados"]] == ["-1003"] and "caiu" in banco["enviados"][0][1]
    assert r["pendentes_reenviados"] == 1
    banco["enviados"].clear()
    TG.process_monitoring_notifications()
    assert banco["enviados"] == []

    # volta: os dois recebem
    entidades[0]["status"] = "up"
    TG.process_monitoring_notifications()
    assert sorted(c for c, _ in banco["enviados"]) == ["-1002", "-1003"]


def test_pendente_vencido_e_descartado(banco, monkeypatch):
    N.salvar_bot_easy("123:abc")
    _grupo(nome="Portaria", chat_id="-1002", sites=["SITE A"])
    _grupo(nome="Tecnicos", chat_id="-1003", sites=["SITE A"])
    entidades = [{"entity_type": "camera", "status": "down", "entity_key": "cam:1", "display_name": "CAM 1",
                  "site": "SITE A", "detail_json": "{}"}]
    monkeypatch.setattr(TG, "list_entities_todas", lambda **k: ([dict(e) for e in entidades], False))
    banco["cai"] = {"-1003"}
    TG.process_monitoring_notifications()
    # voltou antes de Tecnicos receber a queda; Tecnicos volta a funcionar
    entidades[0]["status"] = "up"
    banco["cai"] = set()
    banco["enviados"].clear()
    TG.process_monitoring_notifications()
    textos = [(c, t) for c, t in banco["enviados"]]
    assert not any("caiu" in t for _, t in textos)            # queda velha nao sai
    assert sorted(c for c, t in textos if "voltou" in t) == ["-1002", "-1003"]
