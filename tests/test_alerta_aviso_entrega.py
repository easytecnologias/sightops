"""A3: panico avisa no disparo, registra a entrega e tenta de novo com espera.

SQLite temporario, pessoas ficticias, Telegram falso."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core import permissions, tenant_context
from app.services import alert_store as A
from app.services import db_store
from app.services import notificacoes_service as N

TENANT = "cliente-teste"


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug(TENANT)
    db_store.init_db()
    A._SITE_CONECTOR_CACHE.clear()
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: None)
    disparos = []
    monkeypatch.setattr(A, "notify_async", lambda t, i, r: disparos.append((t, i, r)))
    estado = {"resposta": {"ok": True, "enviados": 2, "destinos": 2, "erros": []}, "chamadas": [], "disparos": disparos}

    def enviar(evento, site, texto, tipo="", urgente=False, tela="monitoring"):
        estado["chamadas"].append(texto)
        return dict(estado["resposta"])

    monkeypatch.setattr(N, "enviar_evento", enviar)
    yield estado
    tenant_context.reset_current_tenant_slug(token)


FALHA = {"ok": False, "enviados": 0, "destinos": 1, "erros": ["Telegram fora"]}


def _alerta(cpf="52998224725"):
    m = A.save_member({"full_name": "Pessoa Teste", "document_id": cpf, "unit_name": "ESCOLA"})
    ctx = {"tenant_slug": TENANT, "member": {"id": m["id"], "full_name": "Pessoa Teste"}}
    return ctx, A.trigger_incident(ctx, {})


def _vencer(inc_id):
    """Adianta o relogio do reenvio sem esperar de verdade."""
    passado = A._iso(A._now_dt() - timedelta(seconds=1))
    with db_store._conn() as c:
        c.execute("UPDATE alert_incidents SET aviso_proximo_at=? WHERE id=?", (passado, inc_id))


def _espera_s(inc_id):
    with db_store._conn() as c:
        prox = c.execute("SELECT aviso_proximo_at FROM alert_incidents WHERE id=?", (inc_id,)).fetchone()[0]
    return prox and round((A.datetime.fromisoformat(prox.replace("Z", "+00:00")) - A._now_dt()).total_seconds())


def test_avisa_no_disparo_uma_vez_so(banco):
    ctx, out = _alerta()
    assert banco["disparos"] == [(TENANT, out["incident"]["id"], "panic")]
    assert out["created"] is True
    A.trigger_incident(ctx, {})                # apertou de novo: mesmo alerta, sem novo aviso
    assert len(banco["disparos"]) == 1


def test_entrega_vai_para_o_incidente_e_o_log(banco):
    _, out = _alerta()
    inc_id = out["incident"]["id"]
    assert A.get_incident(inc_id)["aviso_situacao"] == "sem_tentativa"
    A._send_telegram_for(TENANT, inc_id, "panic")
    inc = A.get_incident(inc_id)
    assert inc["aviso_entregue"] is True and inc["aviso_situacao"] == "entregue" and inc["aviso_entregue_at"]
    assert any(l["action"] == "aviso_entregue" and "2 grupo" in l["note"] for l in inc["log"])


def test_falha_tenta_de_novo_com_espera_crescente_ate_5(banco):
    banco["resposta"] = dict(FALHA)
    _, out = _alerta()
    inc_id = out["incident"]["id"]
    A._send_telegram_for(TENANT, inc_id, "panic")
    esperas = [_espera_s(inc_id)]
    assert A.get_incident(inc_id)["aviso_situacao"] == "tentando"
    assert A.retry_failed_notifications() == []          # ainda nao deu a hora
    for _ in range(3):
        _vencer(inc_id)
        assert len(A.retry_failed_notifications()) == 1
        esperas.append(_espera_s(inc_id))
    assert esperas == [15, 30, 60, 120] or all(abs(a - b) <= 1 for a, b in zip(esperas, (15, 30, 60, 120)))
    _vencer(inc_id)
    A.retry_failed_notifications()                       # quinta e ultima
    inc = A.get_incident(inc_id)
    assert inc["aviso_tentativas"] == 5 and inc["aviso_entregue"] is False
    assert inc["aviso_situacao"] == "nao_entregue" and "Telegram fora" in inc["aviso_erro"]
    assert A.retry_failed_notifications() == [] and len(banco["chamadas"]) == 5
    assert sum(1 for l in inc["log"] if l["action"] == "aviso_falhou") == 5


def test_reenvio_que_entrega_para_de_tentar(banco):
    banco["resposta"] = dict(FALHA)
    _, out = _alerta()
    inc_id = out["incident"]["id"]
    A._send_telegram_for(TENANT, inc_id, "panic")
    banco["resposta"] = {"ok": True, "enviados": 1, "destinos": 1, "erros": []}
    _vencer(inc_id)
    A.retry_failed_notifications()
    inc = A.get_incident(inc_id)
    assert inc["aviso_entregue"] is True and inc["aviso_erro"] == "" and inc["aviso_situacao"] == "entregue"
    assert A.retry_failed_notifications() == []


def test_sem_grupo_nao_fica_tentando(banco):
    banco["resposta"] = {"ok": True, "enviados": 0, "destinos": 0, "erros": []}
    _, out = _alerta()
    inc_id = out["incident"]["id"]
    A._send_telegram_for(TENANT, inc_id, "panic")
    inc = A.get_incident(inc_id)
    assert inc["aviso_situacao"] == "nao_entregue" and "Nenhum grupo" in inc["aviso_erro"]
    assert A.retry_failed_notifications() == []


def test_alerta_encerrado_nao_reenvia(banco):
    banco["resposta"] = dict(FALHA)
    _, out = _alerta()
    inc_id = out["incident"]["id"]
    A._send_telegram_for(TENANT, inc_id, "panic")
    A.transition_incident(inc_id, "close", "op", "resolvido")
    _vencer(inc_id)
    assert A.retry_failed_notifications() == []


def test_escalonamento_nao_diz_enviado_antes_de_enviar(banco):
    banco["resposta"] = dict(FALHA)
    _, out = _alerta()
    inc_id = out["incident"]["id"]
    assert len(A.escalate_unattended(after_s=-1)) == 1
    inc = A.get_incident(inc_id)
    assert inc["aviso_situacao"] == "tentando"
    assert not any("aviso enviado" in l["note"] for l in inc["log"])
    assert A.escalate_unattended(after_s=-1) == []       # escalona uma vez; quem repete e o reenvio
    _vencer(inc_id)
    assert A.retry_failed_notifications()[0]["ok"] is False
    assert "SEM ATENDIMENTO" in banco["chamadas"][-1]


def test_coacao_nao_aparece_para_o_app(banco):
    """A resposta do app e o estado dele nao mudam com a entrega do aviso."""
    banco["resposta"] = dict(FALHA)
    m = A.save_member({"full_name": "Pessoa Teste", "document_id": "52998224725", "unit_name": "ESCOLA"})
    code = A.create_activation_code(m["id"])["code"]
    ctx = A.resolve_app_session(A.activate_app(code, "teste", "web")["token"])
    A.set_app_pins(ctx, "1234", "4321")
    ctx = A.resolve_app_session(A.activate_app(A.create_activation_code(m["id"])["code"], "t", "web")["token"])
    out = A.trigger_incident(ctx, {})
    inc_id = out["incident"]["id"]
    assert set(out["incident"]) == {"id", "opened_at", "attended"}
    assert A.cancel_incident(ctx, inc_id, "4321") == {"ok": True, "tracking": True}
    assert (TENANT, inc_id, "duress") in banco["disparos"]
    A._send_telegram_for(TENANT, inc_id, "duress")
    assert set(A.app_status(ctx)["incident"]) == {"id", "opened_at", "attended"}
    assert not any("aviso" in k for k in A.app_status(ctx))
    inc = A.get_incident(inc_id)
    assert inc["kind"] == "duress" and inc["aviso_situacao"] == "tentando"   # central sabe
    assert "COACAO" in banco["chamadas"][-1]


def test_linhas_antigas_ficam_fora_do_reenvio(banco):
    _, out = _alerta()
    assert A.retry_failed_notifications() == []          # nunca tentado: nada a repetir
    with db_store._conn() as c:
        linha = dict(c.execute("SELECT * FROM alert_incidents WHERE id=?", (out["incident"]["id"],)).fetchone())
    assert (linha["aviso_tentativas"], linha["aviso_proximo_at"], linha["aviso_entregue_at"]) == (0, "", "")


def test_isolamento_entrega_grava_so_no_cliente_certo(banco):
    _, out = _alerta()
    A._registrar_entrega("outro-cliente", out["incident"]["id"], "panic", {"ok": True, "enviados": 1})
    assert A.get_incident(out["incident"]["id"])["aviso_entregue"] is False
