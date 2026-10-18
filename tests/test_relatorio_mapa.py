"""Relatorio do Mapa: areas, pinos que se sobrepoem e mapa sem internet."""
import math

import pytest

from app.services import map_pdf_report as M


def _cam(titulo, lat, lon, status="online"):
    return {"titulo": titulo, "ip": titulo, "status": status, "_pos": (lat, lon)}


def test_nome_base_da_area():
    assert M._chave_area("13 - P. LDD - 01") == "P. LDD"
    assert M._chave_area("21 -ROTATORIA - 02") == "ROTATORIA"
    assert M._chave_area("01 - ENTRADA SIERRA") == "ENTRADA SIERRA"
    assert M._chave_area("") == "SEM NOME"


def test_grupo_pequeno_so_junta_com_vizinho_de_verdade():
    # PORTARIA (1 camera) a ~15 m da entrada: junta. MURO (2) a ~500 m: fica sozinho.
    cams = [
        _cam("02 - ENT VISITANTE - 01", -9.73130, -36.63810),
        _cam("03 - ENT VISITANTE - 02", -9.73133, -36.63812),
        _cam("04 - ENT VISITANTE - 03", -9.73126, -36.63806),
        _cam("07 - PORTARIA", -9.73140, -36.63815),
        _cam("88 - MURO QD. E - 01", -9.73600, -36.63700),
        _cam("89 - MURO QD. E - 02", -9.73610, -36.63705),
    ]
    areas = M.agrupar_areas(cams)
    nomes = {a["nome"]: len(a["cams"]) for a in areas}
    assert nomes == {"ENT VISITANTE / PORTARIA": 4, "MURO QD. E": 2}


def test_pinos_no_mesmo_lugar_sao_afastados_e_ficam_na_imagem():
    pontos = [(100.0, 100.0)] * 5 + [(5.0, 5.0)]
    out = M._afastar(pontos, 40, 400, 300, 20)
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            assert math.hypot(out[i][0] - out[j][0], out[i][1] - out[j][1]) >= 39
    assert all(20 <= x <= 380 and 20 <= y <= 280 for x, y in out)


def test_mapa_sai_mesmo_sem_baixar_tile(monkeypatch):
    monkeypatch.setattr(M, "_tile", lambda *a, **k: None)
    img = M.renderizar_mapa([(-9.7313, -36.6381, "1", M.COR_ONLINE), (-9.7280, -36.6352, "2", M.COR_OFFLINE)],
                            600, 400)
    assert img is not None and img.size == (600, 400)
    assert M.renderizar_mapa([], 600, 400) is None


def test_job_do_mapa_so_responde_para_o_cliente_que_pediu(monkeypatch):
    from fastapi import HTTPException

    from app.api.endpoints import tools
    tools._report_jobs["abc"] = {"kind": "mapa", "tenant": "sierra", "status": "done"}
    try:
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "outro-cliente")
        with pytest.raises(HTTPException):
            tools._map_report_job_do_cliente("abc")
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "sierra")
        assert tools._map_report_job_do_cliente("abc")["tenant"] == "sierra"
    finally:
        tools._report_jobs.pop("abc", None)


def test_rotas_antigas_do_relatorio_nao_entregam_job_do_mapa_nem_de_outro_cliente(monkeypatch):
    from fastapi import HTTPException

    from app.api.endpoints import tools
    tools._report_jobs["mapa1"] = {"kind": "mapa", "tenant": "sierra", "status": "done"}
    tools._report_jobs["inv1"] = {"kind": "inventario", "tenant": "sierra", "status": "done"}
    try:
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "sierra")
        with pytest.raises(HTTPException):
            tools._inventory_report_job_do_cliente("mapa1")
        assert tools._inventory_report_job_do_cliente("inv1")["kind"] == "inventario"
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "outro-cliente")
        with pytest.raises(HTTPException):
            tools._inventory_report_job_do_cliente("inv1")
    finally:
        tools._report_jobs.pop("mapa1", None)
        tools._report_jobs.pop("inv1", None)
