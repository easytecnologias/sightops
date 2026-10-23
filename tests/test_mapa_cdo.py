"""Mapa: CDO (splitter primario) entre a OLT e as CTOs. Dados ficticios.

OLT/PON -> tronco -> CDO -> distribuicao -> CTO. A CTO ligada numa CDO herda
OLT, PON e "vem de"; sem CDO continua como era (direto na OLT)."""
from __future__ import annotations

import json
import zipfile

import pytest
from fastapi import HTTPException

from app.api.endpoints import tools
from app.services.kmz_ops import kmz_to_geojson

PTS = [("CDO-01", -10.0, -36.0), ("CTO - ROSA - 01", -10.001, -36.001), ("CTO - ROSA - 02", -10.002, -36.002),
       ("POP", -10.005, -36.005)]


@pytest.fixture()
def rede(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "_apagar_geradas_do_mapa", lambda *a, **k: None)
    monkeypatch.setattr(tools, "_exige_admin_para_excluir", lambda: None)
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           + "".join(f"<Placemark><name>{n}</name><Point><coordinates>{lo},{la},0</coordinates></Point></Placemark>" for n, la, lo in PTS)
           + "</Document></kml>")
    with zipfile.ZipFile(tmp_path / "c1.kmz", "w") as zf:
        zf.writestr("doc.kml", kml)
    (tmp_path / "c1.geojson").write_text(json.dumps(kmz_to_geojson(tmp_path / "c1.kmz")), encoding="utf-8")
    (tmp_path / "c1.meta.json").write_text(json.dumps({"id": "c1", "label": "JARDINS"}), encoding="utf-8")
    cdo = next(iter(tools._cdo_da_camada("c1", {"ponto": "CDO-01", "lat": -10.0, "lng": -36.0, "splitter": "1:8",
                                                 "bandejas": 2})["cdos"].values()))
    r = tools._cto_da_camada("c1", {"ponto": "CTO - ROSA - 01", "lat": -10.001, "lng": -36.001, "splitter": "1:8",
                                    "olt_key": "olt:velha", "olt_nome": "OLT VELHA", "pon": "9"})
    cto1 = next(iter(r["ctos"].values()))
    r = tools._cto_da_camada("c1", {"ponto": "CTO - ROSA - 02", "lat": -10.002, "lng": -36.002, "splitter": "1:8"})
    cto2 = next(c for c in r["ctos"].values() if c["id"] != cto1["id"])
    return {"cdo": cdo, "cto1": cto1, "cto2": cto2}


def _meta(tmp):
    return json.loads((tmp / "c1.meta.json").read_text(encoding="utf-8"))


def _dist(rede, cto, porta, **kw):
    base = {"tipo": "distribuicao", "de": {"cdo": rede["cdo"]["id"], "porta": porta}, "para": {"cto": cto["id"]},
            "fibras": 12, "fibra": 1, "caminho": [[-10.0, -36.0], [-10.001, -36.001]]}
    base.update(kw)
    return tools._fibra_da_camada("c1", base)


def test_cdo_cadastro_e_portas_pelo_splitter(rede):
    assert rede["cdo"]["portas"] == 8 and rede["cdo"]["bandejas"] == 2
    with pytest.raises(HTTPException):
        tools._cdo_da_camada("c1", {"ponto": "CDO-01", "lat": -10.0, "lng": -36.0, "splitter": "1:3"})
    with pytest.raises(HTTPException):   # outra CDO no mesmo lugar
        tools._cdo_da_camada("c1", {"ponto": "CDO-01", "lat": -10.0, "lng": -36.0, "splitter": "1:8"})


def test_tronco_da_olt_desce_ate_a_cto(rede, tmp_path):
    tools._fibra_da_camada("c1", {"tipo": "tronco", "de": {"olt_key": "olt:7", "olt_nome": "OLT JARDINS", "pon": "5"},
                                  "para": {"cdo": rede["cdo"]["id"]}, "fibras": 24, "fibra": 14,
                                  "caminho": [[-10.005, -36.005], [-10.0, -36.0]]})
    r = _dist(rede, rede["cto1"], 1)
    tronco = next(f for f in r["fibras"].values() if f["tipo"] == "tronco")
    assert (tronco["cor"], tronco["tubo"], tronco["tubo_cor"]) == ("amarela", 2, "amarela")   # fibra 14 = 2a do tubo 2
    cto = r["ctos"][rede["cto1"]["id"]]
    assert (cto["olt_key"], cto["pon"], cto["vem_de"]) == ("olt:7", "5", "CDO-01")
    assert cto["cdo"]["id"] == rede["cdo"]["id"] and cto["cdo"]["porta"] == 1
    # mudar a OLT/PON da CDO desce para a CTO filha
    tools._cdo_da_camada("c1", {"id": rede["cdo"]["id"], "ponto": "CDO-01", "splitter": "1:8", "olt_key": "olt:8", "pon": "2"})
    assert _meta(tmp_path)["ctos"][rede["cto1"]["id"]]["pon"] == "2"
    # salvar a CTO com outra OLT nao desfaz a heranca
    r = tools._cto_da_camada("c1", {"id": rede["cto1"]["id"], "ponto": "CTO - ROSA - 01", "splitter": "1:8", "olt_key": "olt:x", "pon": "7"})
    assert r["ctos"][rede["cto1"]["id"]]["olt_key"] == "olt:8"


def test_porta_e_cto_nao_repetem(rede):
    _dist(rede, rede["cto1"], 1)
    with pytest.raises(HTTPException) as e:
        _dist(rede, rede["cto2"], 1)
    assert "porta 1" in e.value.detail
    with pytest.raises(HTTPException) as e:
        _dist(rede, rede["cto1"], 2)
    assert "ja esta ligada" in e.value.detail
    with pytest.raises(HTTPException):
        _dist(rede, rede["cto2"], 9)          # CDO 1:8 so tem 8 portas
    with pytest.raises(HTTPException):        # encolher a CDO abaixo da porta usada
        _dist(rede, rede["cto2"], 8)
        tools._cdo_da_camada("c1", {"id": rede["cdo"]["id"], "ponto": "CDO-01", "splitter": "1:4"})


def test_cto_sem_cdo_continua_na_olt_e_tirar_o_cabo_solta(rede, tmp_path):
    assert _meta(tmp_path)["ctos"][rede["cto1"]["id"]]["olt_key"] == "olt:velha"   # nada muda sem CDO
    r = _dist(rede, rede["cto1"], 1)
    fid = next(iter(r["fibras"]))
    r = tools._fibra_da_camada("c1", {"id": fid, "excluir": True})
    cto = r["ctos"][rede["cto1"]["id"]]
    assert "cdo" not in cto and cto["vem_de"] == "CDO-01"     # fica com o ultimo valor, sem o vinculo
    _dist(rede, rede["cto1"], 1)
    r = tools._cdo_da_camada("c1", {"id": rede["cdo"]["id"], "excluir": True})
    assert r["fibras"] == {} and "cdo" not in r["ctos"][rede["cto1"]["id"]]


def test_arrastar_cdo_e_cto_leva_as_fibras(rede, tmp_path):
    _dist(rede, rede["cto1"], 1, caminho=[[-10.0, -36.0], [-10.0005, -36.0008], [-10.001, -36.001]])
    tools._editar_ponto_da_camada("c1", {"nome": "CDO-01", "lat": -9.9995, "lon": -35.9995, "lat_atual": -10.0, "lon_atual": -36.0})
    tools._editar_ponto_da_camada("c1", {"nome": "CTO - ROSA - 01", "lat": -10.0012, "lon": -36.0012, "lat_atual": -10.001, "lon_atual": -36.001})
    m = _meta(tmp_path)
    fb = next(iter(m["fibras"].values()))
    assert fb["caminho"][0] == [-9.9995, -35.9995] and fb["caminho"][-1] == [-10.0012, -36.0012]
    assert fb["caminho"][1] == [-10.0005, -36.0008] and m["cdos"][rede["cdo"]["id"]]["lat"] == -9.9995


def test_religar_cabo_existente_exige_admin(rede, monkeypatch):
    r = _dist(rede, rede["cto1"], 1)
    fid = next(iter(r["fibras"]))
    chamou = []
    monkeypatch.setattr(tools, "_exige_admin_para_excluir", lambda: chamou.append(1))
    _dist(rede, rede["cto1"], 1, id=fid, fibra=5)          # so trocar a fibra: livre
    assert chamou == []
    _dist(rede, rede["cto1"], 2, id=fid)                   # mudar de porta = religar
    assert chamou == [1]


def test_caixa_de_passagem_sem_splitter(rede, tmp_path):
    r = tools._cdo_da_camada("c1", {"id": rede["cdo"]["id"], "ponto": "CDO-01", "tipo": "passagem", "splitter": "1:8"})
    cdo = r["cdos"][rede["cdo"]["id"]]
    assert (cdo["tipo"], cdo["splitter"], cdo["portas"]) == ("passagem", "", 0)
    with pytest.raises(HTTPException) as e:        # passagem nao atende CTO por porta
        _dist(rede, rede["cto1"], 1)
    assert "passagem" in e.value.detail
    # com CTO ligada, nao vira passagem sem tirar os cabos
    tools._cdo_da_camada("c1", {"id": rede["cdo"]["id"], "ponto": "CDO-01", "tipo": "splitter", "splitter": "1:8"})
    _dist(rede, rede["cto1"], 1)
    with pytest.raises(HTTPException):
        tools._cdo_da_camada("c1", {"id": rede["cdo"]["id"], "ponto": "CDO-01", "tipo": "passagem"})
