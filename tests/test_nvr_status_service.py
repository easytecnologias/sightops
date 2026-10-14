"""Status de canal de NVR: o que nao deu para ler nunca vira online."""
from __future__ import annotations

from app.services import nvr_status_service as nvr


def test_hikvision_usa_o_estado_do_proprio_nvr():
    assert nvr.decidir(1, "PORTARIA", "10.10.10.5", True, None, set()) == "online"
    assert nvr.decidir(1, "PORTARIA", "10.10.10.5", False, None, {"10.10.10.5"}) == "camera_offline"
    assert nvr.decidir(2, "Canal 2", "", False, None, set()) == "sem_camera"


def test_intelbras_perda_de_video():
    assert nvr.decidir(3, "GALPAO", "", None, {3, 7}, set()) == "camera_offline"
    assert nvr.decidir(4, "GALPAO", "", None, {3, 7}, set()) == "online"


def test_consulta_que_falhou_nao_vira_online():
    # perda = None: nao deu para perguntar ao NVR (a coleta antiga devolvia vazio e tudo ficava online)
    assert nvr.decidir(5, "GALPAO", "10.10.10.9", None, None, set()) == "sem_leitura"
    assert nvr.decidir(5, "GALPAO", "10.10.10.9", None, None, {"10.10.10.9"}) == "online"


def test_perda_de_video_le_indice_base_zero(monkeypatch):
    class R:
        status_code = 200
        text = "channels[0]=2\nchannels[1]=15\n"
    monkeypatch.setattr(nvr.requests, "get", lambda *a, **k: R())
    assert nvr._perda_de_video("http://x", None, 1) == {3, 16}


def test_perda_de_video_sem_resposta_e_none(monkeypatch):
    def falha(*a, **k):
        raise TimeoutError
    monkeypatch.setattr(nvr.requests, "get", falha)
    assert nvr._perda_de_video("http://x", None, 1) is None
