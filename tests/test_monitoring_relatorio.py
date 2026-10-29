"""Linha do tempo do relatorio de disponibilidade (monitoring_relatorio)."""
from datetime import datetime, timedelta, timezone

from app.services.monitoring_relatorio import _linha_do_tempo, _pct, _sem_visibilidade

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


def test_conector_fora_vira_sem_visibilidade_e_nao_queda():
    h = lambda x: INI + timedelta(hours=x)
    # camera caiu 20 min antes do conector ser confirmado fora (10h-14h); voltou junto
    camera = [(h(0), h(9.66), "up"), (h(9.66), h(14), "down"), (h(14), h(24), "up")]
    t = _sem_visibilidade(camera, [(h(10), h(14))])
    assert _soma(t) == {"up": 9.66 + 10, "blind": 14 - 9.66}


def test_camera_que_respondia_antes_do_conector_cair_continua_no_ar():
    h = lambda x: INI + timedelta(hours=x)
    t = _sem_visibilidade([(h(0), h(24), "up")], [(h(10), h(14))])
    assert _soma(t) == {"up": 20, "blind": 4}


def test_queda_logo_apos_o_conector_voltar_e_a_mesma_falha():
    h = lambda x: INI + timedelta(hours=x)
    camera = [(h(0), h(14.03), "up"), (h(14.03), h(14.12), "down"), (h(14.12), h(24), "up")]
    t = _sem_visibilidade(camera, [(h(10), h(14))])
    assert "down" not in _soma(t)
