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


# --- resumo do gravador (o que vai para o monitoramento e o Zabbix) -----------

def _agora_iso(min_atras: float = 0) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=min_atras)).isoformat()


def test_gravador_sem_data_nao_e_online():
    # o caso de producao em 14/10/2026: 803 canais "online" sem data nenhuma
    linhas = [{"status": "online"}, {"status": "online"}]
    r = nvr.resumo_gravador(linhas)
    assert r["status"] == "unknown"
    assert r["canais_online"] == 0 and r["checado_em"] == ""


def test_gravador_julgado_por_todos_os_canais_e_nao_pelo_primeiro():
    linhas = [
        {"status": "online"},  # sem data: nao conta
        {"status": "camera_offline", "status_checked_at": _agora_iso(5)},
        {"status": "online", "status_checked_at": _agora_iso(5)},
        {"status": "sem_camera", "status_checked_at": _agora_iso(5)},
    ]
    r = nvr.resumo_gravador(linhas)
    assert r["status"] == "online"
    # total = so canais com leitura valida (o "online" sem data nao conta)
    assert (r["canais_total"], r["canais_online"], r["canais_offline"]) == (2, 1, 1)


def test_gravador_sem_resposta_e_offline():
    linhas = [{"status": "nvr_offline", "status_checked_at": _agora_iso(3)}] * 4
    assert nvr.resumo_gravador(linhas)["status"] == "offline"


def test_camera_fora_nao_derruba_o_gravador():
    linhas = [{"status": "camera_offline", "status_checked_at": _agora_iso(3)}] * 2
    r = nvr.resumo_gravador(linhas)
    assert r["status"] == "online" and r["canais_offline"] == 2


def test_leitura_velha_e_conector_fora_viram_desconhecido():
    velha = [{"status": "online", "status_checked_at": _agora_iso(180)}]
    assert nvr.resumo_gravador(velha)["status"] == "unknown"
    fora = [{"status": "online", "status_checked_at": _agora_iso(1), "remote_connector_id": "c9"}]
    assert nvr.resumo_gravador(fora, {"c9"})["status"] == "unknown"


def test_zero_chega_ao_zabbix():
    from app.services.zabbix_monitoring_service import _number
    assert _number(0) == 0.0  # antes: None, e "0 canais sem imagem" nunca era enviado
    assert _number(3) == 3.0 and _number("-21,5 dBm") == -21.5
    assert _number(None) is None and _number("") is None and _number(True) is None


def test_painel_conta_canal_de_gravador_certo():
    from app.services.dashboard_service import _status_counts
    linhas = [
        {"channel": 1, "status": "online", "status_checked_at": _agora_iso(5)},
        {"channel": 2, "status": "online"},  # sem data: desconhecido
        {"channel": 3, "status": "camera_offline", "status_checked_at": _agora_iso(5)},
        {"channel": 4, "status": "camera_offline", "status_checked_at": _agora_iso(300)},  # velho
        {"channel": 5, "status": "sem_camera", "status_checked_at": _agora_iso(5)},  # fora da conta
    ]
    assert _status_counts(linhas) == {"total": 4, "online": 1, "offline": 1, "unknown": 2}


# --- isolamento: o laco nao sonda IP real nem conector de outro cliente -------

def _linhas_conector(cid="c1"):
    return [{"channel": 1, "title": "PORTARIA", "remote_connector_id": cid}]


def _sem_rede(monkeypatch):
    from app.api.endpoints import nvr as N
    from app.services import recorder_credentials
    monkeypatch.setattr(recorder_credentials, "resolve_recorder_credential", lambda h, p=0: {"username": "admin", "password": "x"})
    def nao_pode(*a, **k):
        raise AssertionError("nao podia ter sondado o gravador")
    monkeypatch.setattr(N, "_probe_nvr_stack", nao_pode)


def test_conector_de_outro_cliente_nao_e_sondado(monkeypatch):
    import pytest
    from app.services import connector_routing_vnat as vnat
    _sem_rede(monkeypatch)
    monkeypatch.setattr(vnat, "virtual_ip_for", lambda cid, ip: vnat.IP_BLOQUEADO)
    with pytest.raises(RuntimeError, match="nao pertence"):
        nvr._verificar_nvr("192.168.1.10", 80, _linhas_conector(), set())


def test_ip_fora_do_mapa_do_conector_nao_e_sondado(monkeypatch):
    import pytest
    from app.services import connector_routing_vnat as vnat
    _sem_rede(monkeypatch)
    monkeypatch.setattr(vnat, "virtual_ip_for", lambda cid, ip: ip)  # devolveu o IP real
    monkeypatch.setattr(vnat, "has_mapping", lambda cid: True)
    with pytest.raises(RuntimeError, match="fora das LANs"):
        nvr._verificar_nvr("192.168.1.10", 80, _linhas_conector(), set())


def test_sem_leitura_nao_vira_zero_canais_com_imagem():
    # 192.168.1.118 (RADS): o gravador demorou e os 19 canais viraram sem_leitura
    linhas = [{"status": "sem_leitura", "status_checked_at": _agora_iso(2)}] * 19
    r = nvr.resumo_gravador(linhas)
    assert r["status"] == "unknown"
    assert (r["canais_total"], r["canais_online"], r["canais_offline"], r["checado_em"]) == (0, 0, 0, "")
