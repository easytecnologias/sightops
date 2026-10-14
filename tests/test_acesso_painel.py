"""Painel novo do controle de acesso: saude dos avisos, incidentes e recibo."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import access_control_painel as P

AGORA = datetime(2026, 10, 14, 21, 0, tzinfo=timezone.utc)


def _msg(min_atras, status, erro="", numero="5582999990000"):
    t = (AGORA - timedelta(minutes=min_atras)).strftime("%Y-%m-%d %H:%M:%S.000000+00")
    return {"contact_number": numero, "status": status, "error": erro, "created_at": t, "updated_at": t}


def test_alerta_quando_meta_recusa_mesmo_com_canal_conectado(monkeypatch):
    """O caso de 15/09 a 07/10: token valido, envios recusados por pagamento."""
    msgs = [_msg(i, "failed", "Business eligibility payment issue") for i in range(12)] + [_msg(1, "read")]
    monkeypatch.setattr(P, "_mensagens", lambda desde: [m for m in msgs if m["created_at"] >= P._utc_txt(desde)])
    s = P.saude_avisos(agora=AGORA)
    assert s["alerta"] is True
    assert s["falhas"] == 12 and s["enviados"] == 13
    assert s["erro_principal"] == "Business eligibility payment issue"


def test_pouco_volume_nao_vira_alarme(monkeypatch):
    msgs = [_msg(3, "failed", "Message undeliverable"), _msg(2, "read")]
    monkeypatch.setattr(P, "_mensagens", lambda desde: msgs)
    assert P.saude_avisos(agora=AGORA)["alerta"] is False


def test_envio_normal_nao_alerta(monkeypatch):
    msgs = [_msg(i, "read") for i in range(30)] + [_msg(5, "failed", "Message undeliverable")]
    monkeypatch.setattr(P, "_mensagens", lambda desde: msgs)
    assert P.saude_avisos(agora=AGORA)["alerta"] is False


def _consulta(msgs):
    return lambda desde: [m for m in msgs if m["created_at"] >= P._utc_txt(desde)]


def test_noite_sem_envio_nao_recupera_canal_bloqueado(monkeypatch):
    """Bloqueio de pagamento: a tarde falhou tudo; de noite ninguem passa.
    O canal nao pode voltar a online so porque a janela de 30 min ficou vazia."""
    msgs = [_msg(300 + i, "failed", "Business eligibility payment issue") for i in range(25)]
    monkeypatch.setattr(P, "_mensagens", _consulta(msgs))
    s = P.saude_avisos(agora=AGORA)
    assert s["alerta"] is True and s["enviados"] == 20


def test_noite_tranquila_com_avisos_entregues_nao_alerta(monkeypatch):
    msgs = [_msg(300 + i, "read") for i in range(25)] + [_msg(310, "failed", "Message undeliverable")]
    monkeypatch.setattr(P, "_mensagens", _consulta(msgs))
    assert P.saude_avisos(agora=AGORA)["alerta"] is False


def test_incidentes_juntam_dias_vizinhos_e_trazem_o_motivo():
    def dia(d, n_falha, n_ok, erro="Business eligibility payment issue"):
        base = f"2026-09-{d:02d} 12:00:00"
        return ([{"status": "failed", "error": erro, "created_at": base}] * n_falha
                + [{"status": "read", "error": "", "created_at": base}] * n_ok)
    msgs = dia(15, 120, 2) + dia(16, 110, 0) + dia(18, 100, 5) + dia(22, 0, 150) + dia(29, 90, 3)
    inc = P._incidentes(msgs)
    assert [(i["inicio"], i["fim"]) for i in inc] == [("2026-09-15", "2026-09-18"), ("2026-09-29", "2026-09-29")]
    assert inc[0]["falhas"] == 330 and inc[0]["erro"] == "Business eligibility payment issue"


@pytest.mark.parametrize("bruto, esperado", [
    ("(82) 9 9812-0000", "5582998120000"),
    ("5582998120000", "5582998120000"),
    ("", ""),
])
def test_numero_igual_ao_do_log(bruto, esperado):
    assert P._numero(bruto) == esperado


def test_classe_dos_status():
    assert [P._classe(s) for s in ("read", "delivered", "sent", "whatsapp_sent", "failed", "whatsapp_failed")] == \
        ["lido", "entregue", "enviado", "enviado", "falha", "falha"]


def test_hora_local_do_leitor_casa_com_utc_do_whatsapp():
    """Leitor grava 18:43 local; o aviso sai 21:43 UTC -- e o mesmo instante."""
    assert P._ler_local("2026-10-14 18:43:15") == P._ler_utc("2026-10-14 21:43:15.123+00")
