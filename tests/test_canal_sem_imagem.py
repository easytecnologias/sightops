"""Camera no ar e gravador sem imagem dela: o canal nao pode aparecer "online".

Caso real, SIERRA, 19/10/2026: o NVR 01 (10.200.0.212) ficou sem imagem de 14
cameras que respondiam na rede. A tela de Gravadores mostrava 48/48 online,
o monitoramento dava o NVR como "up" e ninguem foi avisado -- so o relatorio
em PDF, que lia o status cru, mostrou.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import nvr_status_service as nvr
from app.services import status_efetivo as se
from app.services.pdf_inventory_report import _recorder_channel_offline, _recorder_channel_status


def _iso(min_atras: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=min_atras)).isoformat()


def _canal(status="camera_offline", ip="10.200.1.13", idade=10, fonte="verificacao_leve", **extra):
    return {"host": "10.200.0.212", "channel": int(ip.rsplit(".", 1)[1]), "camera_ip": ip,
            "status": status, "status_checked_at": _iso(idade), "status_source": fonte,
            "camera_mac": "ff:ff:ff:ff:ff:ff", **extra}


def _medidas(status="online", mac="8c:22:d2:fb:18:78", ip="10.200.1.13"):
    return {ip: {"status": status, "status_checked_at": _iso(1), "modo": "olt", "mac": mac}}


def test_camera_no_ar_e_gravador_sem_imagem_vira_sem_imagem():
    linha = se.herdar_da_camera(_canal(), _medidas())
    assert linha["status"] == se.SEM_IMAGEM
    assert linha["status_origem"] == "gravador"
    assert linha["status_motivo"] == se.MOTIVO_SEM_IMAGEM
    assert linha["status_gravador"] == "camera_offline"
    # e continua valendo depois do filtro de idade (ciclo do NVR ~40 min > 30 min da camera)
    linha = se.herdar_da_camera(_canal(idade=45), _medidas())
    assert se.aplicar_em_linha(linha, set())["status"] == se.SEM_IMAGEM


def test_camera_fora_de_verdade_segue_offline():
    linha = se.herdar_da_camera(_canal(), _medidas(status="offline"))
    assert linha["status"] == "offline"


def test_gravador_com_imagem_herda_online_da_camera():
    linha = se.herdar_da_camera(_canal(status="online"), _medidas())
    assert linha["status"] == "online"


def test_sem_leitura_do_gravador_nao_vira_sem_imagem():
    # o gravador so demorou: nao ha prova de que ficou sem imagem
    assert se.herdar_da_camera(_canal(status="sem_leitura"), _medidas())["status"] == "online"
    # leitura do gravador velha demais (mais de 2 h) tambem nao prova nada
    assert se.herdar_da_camera(_canal(idade=180), _medidas())["status"] == "online"
    # status que veio da varredura, nao da verificacao do gravador
    assert se.herdar_da_camera(_canal(fonte="scan"), _medidas())["status"] == "online"


def test_conector_fora_vira_nao_verificado():
    linha = se.herdar_da_camera(_canal(remote_connector_id="c1"), _medidas())
    assert se.aplicar_em_linha(linha, {"c1"})["status"] == "unknown"


def test_mac_medido_na_rede_vence_o_do_gravador():
    # NVR 01: o Intelbras devolve ff:ff:ff:ff:ff:ff em canal ONVIF
    linha = se.herdar_da_camera(_canal(status="online"), _medidas())
    assert linha["camera_mac"] == linha["mac_camera"] == linha["mac"] == "8c:22:d2:fb:18:78"
    # NVR 02: canal 9 (camera .49) gravado com o MAC da camera .36
    errado = _canal(status="online", ip="10.200.1.49", camera_mac="54:ba:d9:e1:cd:a9")
    linha = se.herdar_da_camera(errado, _medidas(mac="8c:22:d2:fb:18:93", ip="10.200.1.49"))
    assert linha["camera_mac"] == "8c:22:d2:fb:18:93"
    assert linha["camera_mac_gravador"] == "54:ba:d9:e1:cd:a9"
    # sem MAC medido, fica o do gravador
    linha = se.herdar_da_camera(_canal(status="online", camera_mac="aa:bb:cc:dd:ee:ff"), _medidas(mac=""))
    assert linha["camera_mac"] == "aa:bb:cc:dd:ee:ff"


def test_gravador_com_camera_no_ar_sem_imagem_fica_instavel():
    linhas = [_canal(ip=f"10.200.1.{n}") for n in (13, 14)] + [_canal(status="online", ip="10.200.1.1")]
    medidas = {**_medidas(ip="10.200.1.13"), **_medidas(ip="10.200.1.14"), **_medidas(ip="10.200.1.1")}
    r = nvr.resumo_gravador(linhas, medidas=medidas)
    assert r["status"] == "unstable"
    assert r["canais_sem_imagem"] == 2 and r["canais_sem_imagem_lista"] == [13, 14]
    # camera fora de verdade nao deixa o gravador instavel: quem avisa e a camera
    r = nvr.resumo_gravador([_canal()], medidas=_medidas(status="offline"))
    assert r["status"] == "online" and r["canais_sem_imagem"] == 0
    # sem as medidas das cameras, o comportamento antigo
    assert nvr.resumo_gravador(linhas)["status"] == "online"
    # conector caido: nao da para afirmar nada sobre o canal
    fora = [_canal(remote_connector_id="c1")]
    assert nvr.resumo_gravador(fora, {"c1"}, medidas=_medidas())["canais_sem_imagem"] == 0


def test_relatorio_mostra_sem_imagem_e_conta_como_offline():
    linha = {"status": "sem_imagem", "camera_ip": "10.200.1.13", "title": "13 - P. LDD - 01"}
    assert _recorder_channel_status(linha) == "sem imagem no gravador"
    assert _recorder_channel_offline(linha)
    assert _recorder_channel_status({"status": "unknown"}) == "nao verificado"
