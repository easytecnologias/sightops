"""Ao vivo: senha salva RECUSADA pela camera (e sem alternativa) -> pede a
senha ao operador, em vez de seguir e falhar mudo. UNV de Porto Real
(21/10/2026): a prova de senha nao sabia testar UNV (404 = "inconclusivo") e o
RTSP da UNV fica mudo com senha errada -- o go2rtc so dizia "Invalid data"."""
from app.api.endpoints import maintenance as M


def _base(monkeypatch, aceita):
    monkeypatch.setattr(M, "resolve_camera_password", lambda ip, u, p, c="": ("admin", p or "salva-errada"))
    monkeypatch.setattr(M, "_reach", lambda ip, c="": "10.211.128.105")
    monkeypatch.setattr(M, "_senha_aceita", lambda alvo, u, s: aceita(s))
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip, c="": {"mac": "c4:79:05:b8:00:44", "site": "PORTO REAL"})
    import app.services.camera_credentials as cc
    monkeypatch.setattr(cc, "resolve_camera_credential", lambda mac, site: {"username": "admin", "password": "salva-errada"})


def test_unv_tem_prova_de_senha():
    assert any("LAPI" in p for p in M._PROVAS_DE_SENHA)


def test_ao_vivo_pede_senha_quando_a_camera_recusa(monkeypatch):
    _base(monkeypatch, lambda s: False)
    assert M._credencial_que_responde("10.45.0.105", "", "", "", pedir_se_recusada=True) == ("admin", "")
    # outros usos (troca de IP) seguem como antes
    assert M._credencial_que_responde("10.45.0.105", "", "", "") == ("admin", "salva-errada")


def test_senha_aceita_ou_digitada_segue(monkeypatch):
    _base(monkeypatch, lambda s: True)
    assert M._credencial_que_responde("10.45.0.105", "", "", "", pedir_se_recusada=True) == ("admin", "salva-errada")
    _base(monkeypatch, lambda s: False)
    assert M._credencial_que_responde("10.45.0.105", "", "digitada", "", pedir_se_recusada=True) == ("admin", "digitada")
