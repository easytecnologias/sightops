"""Histerese do estado no monitoramento (monitoring_service._decidir_com_histerese).

Em 26/10/2026 as 4 cameras atras da ONU 4431DEFF (RESERVA, PERUCABA) perdiam
UM ping a cada ~6 min: cada perda virava "unstable" e a leitura seguinte
"up" -- 80 trocas de estado por camera em 24 h, mais 87 dos gravadores delas.
"""
from datetime import datetime, timedelta, timezone

from app.services import monitoring_service as M


def _rodar(leituras, inicio_status="up", passo_min=2, threshold=2):
    """Aplica leituras cruas (uma a cada `passo_min`) e devolve os estados."""
    t0 = datetime.now(timezone.utc) - timedelta(minutes=passo_min * len(leituras))
    status, falhas, osc = inicio_status, 0, {"falhas": [], "ok_seguidos": 0, "instavel_seguidas": 0}
    estados = []
    for i, raw in enumerate(leituras):
        agora = (t0 + timedelta(minutes=passo_min * i)).isoformat()
        status, falhas = M._decidir_com_histerese(raw, status, falhas, threshold, osc, agora)
        estados.append(status)
    return estados


def _trocas(estados, inicio="up"):
    anterior, n = inicio, 0
    for e in estados:
        n += e != anterior
        anterior = e
    return n


def test_uma_falha_isolada_nao_gera_evento():
    estados = _rodar(["up"] * 5 + ["down"] + ["up"] * 5)
    assert _trocas(estados) == 0


def test_camera_que_perde_um_ping_a_cada_6_min_gera_um_aviso_so():
    # 3 h de leituras a cada 2 min: uma falha a cada 3 leituras (o padrao da RESERVA)
    leituras = (["up", "up", "down"] * 30)
    estados = _rodar(leituras)
    assert "unstable" in estados and "down" not in estados
    assert _trocas(estados) == 1          # antes: 60 trocas


def test_queda_de_verdade_continua_virando_down_na_segunda_falha():
    estados = _rodar(["up", "down", "down", "down"])
    assert estados[1] != "down" and estados[2] == "down"


def test_volta_de_queda_exige_duas_leituras_boas():
    estados = _rodar(["down", "down", "up", "up"])
    assert estados[1] == "down" and estados[2] == "down" and estados[3] == "up"


def test_oscilacao_acaba_depois_de_30_min_sem_falha():
    estados = _rodar(["up", "up", "down"] * 3 + ["up"] * 20)
    assert estados[8] == "unstable"
    assert estados[-1] == "up"
    assert _trocas(estados) == 2


def test_instavel_vindo_do_gravador_precisa_repetir():
    assert _rodar(["up", "unstable", "up"]) == ["up", "up", "up"]
    assert _rodar(["up", "unstable", "unstable"])[-1] == "unstable"


def test_manutencao_nao_vira_desconhecido_por_uma_falha():
    assert _rodar(["down"], inicio_status="maintenance") == ["maintenance"]


def test_queda_longa_volta_direto_para_up():
    # Revisor do Zabbix: link fora 5 leituras ficava "unstable" 30 min depois de
    # voltar (todas as falhas contavam como oscilacao) e o "caiu" nao fechava.
    estados = _rodar(["up"] * 3 + ["down"] * 5 + ["up"] * 3, passo_min=1)
    assert estados[-1] == "up" and "unstable" not in estados


def test_oscilou_e_depois_caiu_sai_da_queda_como_instavel():
    estados = _rodar(["up", "up", "down"] * 4 + ["down", "down", "up", "up"])
    assert "down" in estados and estados[-1] == "unstable"


def test_gravador_so_publica_canais_sem_imagem_com_instavel_confirmado(monkeypatch):
    gravado = {}

    class Con:
        def execute(self, sql, params=()):
            if sql.startswith("INSERT INTO monitoring_entities"):
                gravado["detail"] = params[16]
            return self

        def fetchone(self):
            return None

    item = {"entity_key": "nvr:x:10.0.0.1", "entity_type": "nvr", "status": "unstable",
            "detail": {"canais_sem_imagem": 2, "canais_sem_imagem_lista": [3, 7], "motivo": "2 camera(s)..."}}
    r = M._observe_entity_on(Con(), item, "t")   # 1a leitura "unstable": ainda nao confirmado
    import json
    d = json.loads(gravado["detail"])
    assert r["status"] == "unknown" and d["canais_sem_imagem"] == 0 and d["canais_sem_imagem_lista"] == []
    assert d["canais_sem_imagem_lido"] == [3, 7] and "motivo" not in d


def test_site_do_gravador_e_o_da_maioria_dos_canais():
    # NVD RESERVA 01: canal 1 com local PERUCABA levava o gravador inteiro para la.
    canais = [{"channel": 1, "local": "PERUCABA", "site": "RESERVA"}] + [{"channel": i, "local": "RESERVA", "site": "RESERVA"} for i in range(2, 33)]
    assert M._site_do_gravador(canais) == "RESERVA"
    assert M._site_do_gravador([{"local": "PERUCABA"}] + [{"local": "RESERVA"}] * 3) == "RESERVA"
    assert M._site_do_gravador([{}]) == ""
