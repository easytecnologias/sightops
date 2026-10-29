"""Linha do tempo do relatorio de disponibilidade (monitoring_relatorio)."""
from datetime import datetime, timedelta, timezone

from app.services.monitoring_relatorio import _linha_do_tempo, _pct

INI = datetime(2026, 10, 1, 3, tzinfo=timezone.utc)
FIM = INI + timedelta(days=1)


def _ev(horas, de, para):
    return {"from_status": de, "to_status": para, "created_at": (INI + timedelta(hours=horas)).isoformat()}


def _soma(trechos):
    s = {}
    for a, b, est in trechos:
        s[est] = s.get(est, 0) + (b - a).total_seconds() / 3600
    return s


def test_estado_antes_do_periodo_vale_ate_o_primeiro_evento():
    ev = {"antes": {"to_status": "up"}, "dentro": [_ev(6, "up", "down"), _ev(8, "down", "up")], "depois": None}
    assert _soma(_linha_do_tempo({}, ev, INI, FIM)) == {"up": 22, "down": 2}


def test_sem_evento_antes_usa_o_de_do_primeiro_evento():
    ev = {"antes": None, "dentro": [_ev(12, "down", "up")], "depois": None}
    assert _soma(_linha_do_tempo({}, ev, INI, FIM)) == {"down": 12, "up": 12}


def test_sem_evento_no_periodo_usa_o_primeiro_depois():
    ev = {"antes": None, "dentro": [], "depois": {"from_status": "up"}}
    assert _soma(_linha_do_tempo({}, ev, INI, FIM)) == {"up": 24}


def test_sem_evento_nenhum_vale_o_estado_atual_desde_a_ultima_mudanca():
    ent = {"status": "up", "last_changed_at": (INI + timedelta(hours=4)).isoformat()}
    ev = {"antes": None, "dentro": [], "depois": None}
    assert _soma(_linha_do_tempo(ent, ev, INI, FIM)) == {"unknown": 4, "up": 20}


def test_disponibilidade_ignora_tempo_sem_medida():
    assert _pct(0, 0) is None
    assert _pct(3600, 36000) == 90.0
