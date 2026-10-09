"""Classificacao de trechos: decodificacao do YOLOX, filtro de objeto fixo e o job.

Sem rede e sem o arquivo do modelo: a saida do YOLOX e montada a mao e o
gravador e o detector sao falsos.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import numpy as np
import pytest

from app.core import tenant_context
from app.services import investigation_classify as ic
from app.services import motion_classifier as mc


def _saida_com(alvos, lado=640):
    """Saida crua (1, N, 85) com uma ancora 'acesa' por alvo (classe, conf, cx, cy, w, h em px)."""
    grade, passos = mc.Detector._grades(lado)
    p = np.full((grade.shape[0], 85), -9.0, dtype=np.float32)
    p[:, 4] = 0.0
    for i, (classe, conf, cx, cy, w, h) in enumerate(alvos):
        idx = 100 + i * 997  # ancoras do passo 8, bem separadas
        s = passos[idx, 0]
        p[idx, 0], p[idx, 1] = cx / s - grade[idx, 0], cy / s - grade[idx, 1]
        p[idx, 2], p[idx, 3] = np.log(w / s), np.log(h / s)
        p[idx, 4] = 1.0
        p[idx, 5:] = 0.0
        p[idx, 5 + classe] = conf
    return p[None], grade, passos


def test_decodifica_pessoa_e_carro_na_posicao_certa():
    saida, grade, passos = _saida_com([(0, 0.8, 320, 200, 40, 120), (2, 0.9, 100, 400, 120, 60)])
    # imagem original 1280x720 -> r = 0.5
    ds = mc.decodificar(saida, 0.5, 1280, 720, grade, passos)
    por = {d.classe: d for d in ds}
    assert set(por) == {"pessoa", "carro"}
    p = por["pessoa"]
    assert abs((p.x1 + p.x2) / 2 - 640 / 1280) < 0.01 and abs((p.y1 + p.y2) / 2 - 400 / 720) < 0.01
    assert mc.rotulo(ds) == "pessoa"


def test_corte_por_classe():
    # pessoa 0,32 passa (corte 0,30); carro 0,35 nao passa (corte 0,40); cadeira (56) nunca
    saida, grade, passos = _saida_com([(0, 0.32, 320, 200, 40, 120), (2, 0.35, 100, 400, 120, 60), (56, 0.9, 500, 500, 50, 50)])
    ds = mc.decodificar(saida, 1.0, 640, 640, grade, passos)
    assert [d.classe for d in ds] == ["pessoa"]


def test_deteccao_vira_json_puro():
    import json
    saida, grade, passos = _saida_com([(0, 0.8, 320, 200, 40, 120)])
    ds = mc.decodificar(saida, 0.5, 1280, 720, grade, passos)
    json.dumps(mc.como_dict(ds))  # numpy.float32 aqui quebrava o cache


def test_so_veiculo_e_nada():
    saida, grade, passos = _saida_com([(7, 0.7, 300, 300, 200, 100)])
    assert mc.rotulo(mc.decodificar(saida, 1.0, 640, 640, grade, passos)) == "veiculo"
    vazio, _, _ = _saida_com([])
    assert mc.rotulo(mc.decodificar(vazio, 1.0, 640, 640, grade, passos)) == "movimento"


def _pessoa(x=0.5, y=0.5):
    return mc.Deteccao("pessoa", 0.6, x, y, x + 0.05, y + 0.2)


def test_objeto_fixo_vira_cenario_e_pessoa_que_anda_fica():
    por, inst = {}, {}
    base = datetime(2026, 10, 9, 0, 0, 0).timestamp()
    for i in range(6):  # macacao pendurado: mesmo lugar, 6 trechos em 50 min
        por[f"t{i}"] = [_pessoa(0.5, 0.5)]
        inst[f"t{i}"] = base + i * 600
    por["andando"] = [_pessoa(0.1, 0.3)]
    inst["andando"] = base + 100
    assert mc.marcar_fixos(por, inst) == 6
    assert all(d.fixo for i in range(6) for d in por[f"t{i}"])
    assert mc.rotulo(por["t0"]) == "movimento" and mc.rotulo(por["andando"]) == "pessoa"


def test_repetido_em_pouco_tempo_nao_e_fixo():
    # mesma pessoa parada 5 trechos seguidos em 4 min: e alguem de verdade
    por = {f"t{i}": [_pessoa()] for i in range(5)}
    inst = {f"t{i}": i * 60.0 for i in range(5)}
    assert mc.marcar_fixos(por, inst) == 0


def test_instantes_do_trecho():
    ini = datetime(2026, 10, 9, 2, 13, 0)
    assert ic.instantes_do_trecho(ini, ini + timedelta(seconds=30)) == [ini + timedelta(seconds=10)]
    assert ic.instantes_do_trecho(ini, ini + timedelta(seconds=120)) == [ini + timedelta(seconds=10), ini + timedelta(seconds=60)]
    assert ic.instantes_do_trecho(ini, ini + timedelta(seconds=4)) == [ini + timedelta(seconds=4)]


class _DetectorFalso:
    def __init__(self, respostas):
        self.respostas = respostas

    def detectar(self, img):
        return []


@pytest.fixture()
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    ic._CACHES.clear()
    token = tenant_context.set_current_tenant_slug("cliente-a")
    yield tmp_path
    tenant_context.reset_current_tenant_slug(token)


def test_job_classifica_e_pessoa_em_qualquer_quadro_vence(ambiente, monkeypatch):
    # quadro das 02:13:10 tem pessoa; o de 02:14:00 so carro; o trecho das 03:00 nada; 04:00 o gravador falha
    respostas = {
        "02:13:10": [mc.Deteccao("carro", 0.8, 0.1, 0.1, 0.3, 0.3)],
        "02:14:00": [_pessoa()],
        "03:00:10": [],
    }
    monkeypatch.setattr(mc, "detector", lambda: _DetectorFalso(respostas))

    tenants_vistos = set()

    def classificar(host, canal, m, url):
        tenants_vistos.add(tenant_context.get_current_tenant_slug())
        chave = m.strftime("%H:%M:%S")
        return None if chave.startswith("04") else respostas.get(chave, [])
    monkeypatch.setattr(ic, "classificar_quadro", classificar)

    trechos = [{"ini": "2026-10-09 02:13:00", "fim": "2026-10-09 02:15:00"},
               {"ini": "2026-10-09 03:00:00", "fim": "2026-10-09 03:00:40"},
               {"ini": "2026-10-09 04:00:00", "fim": "2026-10-09 04:00:30"}]
    job = ic.iniciar("10.10.9.120", 1, trechos, lambda m: "rtsp://x")
    for _ in range(100):
        if ic.situacao(job)["status"] in ("pronto", "erro"):
            break
        time.sleep(0.05)
    sit = ic.situacao(job)
    assert sit["status"] == "pronto" and sit["feito"] == 3 and "tenant" not in sit
    # o quadro e tirado em thread auxiliar: tem que continuar no cliente certo
    assert tenants_vistos == {"cliente-a"}
    assert (ambiente / "tenants" / "cliente-a" / "investigacao_classes").exists()
    r = ic.resultados("10.10.9.120", 1, trechos)
    assert r["2026-10-09 02:13:00"]["rotulo"] == "pessoa"
    assert r["2026-10-09 02:13:00"]["foto"] == "2026-10-09 02:14:00"
    assert r["2026-10-09 03:00:00"]["rotulo"] == "movimento"
    assert r["2026-10-09 04:00:00"]["rotulo"] == "sem_imagem"


def test_job_de_um_cliente_nao_aparece_para_outro(ambiente, monkeypatch):
    monkeypatch.setattr(mc, "detector", lambda: _DetectorFalso({}))
    monkeypatch.setattr(ic, "classificar_quadro", lambda *a: [])
    job = ic.iniciar("10.10.9.120", 1, [{"ini": "2026-10-09 02:13:00", "fim": "2026-10-09 02:13:30"}], lambda m: "x")
    tenant_context.set_current_tenant_slug("cliente-b")
    with pytest.raises(KeyError):
        ic.situacao(job)
    assert ic.resultados("10.10.9.120", 1, [{"ini": "2026-10-09 02:13:00", "fim": "2026-10-09 02:13:30"}]) == {}


def test_sem_modelo_o_job_explica(ambiente, monkeypatch):
    def sem():
        raise FileNotFoundError("modelo /app/data/modelos/yolox_m.onnx nao encontrado")
    monkeypatch.setattr(mc, "detector", sem)
    job = ic.iniciar("10.10.9.120", 1, [{"ini": "2026-10-09 02:13:00", "fim": "2026-10-09 02:13:30"}], lambda m: "x")
    for _ in range(100):
        if ic.situacao(job)["status"] == "erro":
            break
        time.sleep(0.05)
    assert "detector nao instalado" in ic.situacao(job)["erro"]
