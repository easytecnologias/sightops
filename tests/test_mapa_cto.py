"""Mapa: CTO com splitter, origem e ONU por porta, gravada no meta da camada. Dados ficticios."""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.api.endpoints import tools
from app.core import tenant_context as T

_CAMINHO = [[-10.0, -36.0], [-10.0009, -36.0]]


@pytest.fixture()
def camada(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path)
    (tmp_path / "c1.kmz").write_bytes(b"kmz")
    (tmp_path / "c1.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    (tmp_path / "c1.meta.json").write_text(json.dumps({"id": "c1", "label": "PORTO", "cor_outros": "#123456"}), encoding="utf-8")
    return tmp_path


def _cto(**kw):
    base = {"ponto": "CTO - VERDE - 01", "lat": -10.0009, "lng": -36.0, "splitter": "1:8", "nivel": "secundario",
            "olt_nome": "OLT 1", "pon": "0/3", "vem_de": "CDO-01"}
    base.update(kw)
    r = tools._cto_da_camada("c1", base, "op")
    return r["ctos"][kw["id"]] if kw.get("id") else next(iter(r["ctos"].values()))


def test_cadastra_cto_e_portas(camada):
    c = _cto(portas_info={"1": {"onu_key": "onu:a|1|5", "onu_nome": "ONU 5"}, "3": {"obs": "reservada"}})
    assert c["portas"] == 8 and c["splitter"] == "1:8" and c["pon"] == "0/3" and c["vem_de"] == "CDO-01"
    assert c["portas_info"]["1"]["onu_key"] == "onu:a|1|5" and c["portas_info"]["3"]["obs"] == "reservada"
    meta = json.loads((camada / "c1.meta.json").read_text(encoding="utf-8"))
    assert meta["cor_outros"] == "#123456" and c["id"] in meta["ctos"]
    # editar mantem o id e quem criou
    c2 = _cto(id=c["id"], splitter="1:16")
    assert c2["portas"] == 16 and c2["criado_por"] == "op" and c2["portas_info"] == {}
    # o mesmo ponto, no mesmo lugar, nao vira segunda CTO
    with pytest.raises(HTTPException) as e:
        _cto()
    assert "ja e uma CTO" in e.value.detail


def test_validacoes(camada):
    with pytest.raises(HTTPException):
        _cto(splitter="1:9")
    with pytest.raises(HTTPException) as e:
        _cto(portas_info={"9": {"onu_key": "x"}})
    assert "fora da CTO" in e.value.detail
    with pytest.raises(HTTPException) as e:
        _cto(portas_info={"1": {"onu_key": "x", "onu_nome": "A"}, "2": {"onu_key": "x", "onu_nome": "A"}})
    assert "duas portas" in e.value.detail


def test_caixa_ocupa_porta_e_trava_encolher(camada):
    c = _cto()
    cx = next(iter(tools._caixa_da_camada("c1", {"ponto": "CAI", "nome": "CAI-01", "tipo": "onu", "portas": 4}, "op")["caixas"].values()))
    cx2 = next(v for v in tools._caixa_da_camada("c1", {"ponto": "CAI2", "nome": "CAI-02", "tipo": "onu", "portas": 4}, "op")["caixas"].values() if v["nome"] == "CAI-02")
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "cto": {"ponto": "CTO - VERDE - 01", "porta": 7}, "tipo": "drop", "caminho": _CAMINHO})
    # outra caixa na mesma porta: recusa
    with pytest.raises(HTTPException) as e:
        tools._cabo_da_camada("c1", {"caixa": cx2["id"], "cto": {"ponto": "CTO - VERDE - 01", "porta": 7}, "tipo": "drop", "caminho": _CAMINHO})
    assert "ja tem a caixa CAI-01" in e.value.detail
    # a CTO nao encolhe abaixo da porta 7
    with pytest.raises(HTTPException) as e:
        _cto(id=c["id"], splitter="1:4")
    assert "porta 7" in e.value.detail


def test_excluir_so_admin(camada, monkeypatch):
    c = _cto()
    from app.core import permissions
    monkeypatch.setattr(permissions, "pode_excluir", lambda: False)
    with pytest.raises(HTTPException):
        tools._cto_da_camada("c1", {"id": c["id"], "excluir": True})
    monkeypatch.setattr(permissions, "pode_excluir", lambda: True)
    assert tools._cto_da_camada("c1", {"id": c["id"], "excluir": True})["ctos"] == {}


@pytest.fixture()
def camada_kmz(tmp_path, monkeypatch):
    """Camada com KMZ de verdade: C.CFTV-01 e C.CFTV-02 (caixas) e CTO-07."""
    import zipfile
    from app.services.kmz_ops import kmz_to_geojson
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "_apagar_geradas_do_mapa", lambda *a, **k: None)
    pts = [("C.CFTV-01", -10.0, -36.0), ("C.CFTV-02", -10.001, -36.001), ("CTO-07", -10.002, -36.002)]
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           + "".join(f"<Placemark><name>{n}</name><Point><coordinates>{lo},{la},0</coordinates></Point></Placemark>" for n, la, lo in pts)
           + "</Document></kml>")
    with zipfile.ZipFile(tmp_path / "c1.kmz", "w") as zf:
        zf.writestr("doc.kml", kml)
    (tmp_path / "c1.geojson").write_text(json.dumps(kmz_to_geojson(tmp_path / "c1.kmz")), encoding="utf-8")
    (tmp_path / "c1.meta.json").write_text(json.dumps({"id": "c1", "label": "JARDINS"}), encoding="utf-8")
    return tmp_path


def _nomes(pasta):
    return sorted(f["properties"]["name"] for f in json.loads((pasta / "c1.geojson").read_text(encoding="utf-8"))["features"])


def test_renomear_caixa_renomeia_o_ponto(camada_kmz):
    r = tools._caixa_da_camada("c1", {"ponto": "C.CFTV-02", "nome": "C.CFTV-02", "tipo": "passagem", "lat": -10.001, "lng": -36.001})
    cx2 = next(iter(r["caixas"].values()))
    # trocar para um nome livre: o ponto vai junto
    r = tools._caixa_da_camada("c1", {"id": cx2["id"], "ponto": "C.CFTV-02", "nome": "C.CFTV-03", "tipo": "passagem"})
    assert r["aviso"] == "" and r["caixas"][cx2["id"]]["ponto"] == "C.CFTV-03"
    assert _nomes(camada_kmz) == ["C.CFTV-01", "C.CFTV-03", "CTO-07"]
    # nome de outro ponto: recusa SEM gravar (gravar "assim mesmo" deixava a
    # caixa com um nome que o mapa nao tem naquele lugar -- ela sumia da tela)
    with pytest.raises(HTTPException) as e:
        tools._caixa_da_camada("c1", {"id": cx2["id"], "ponto": "C.CFTV-03", "nome": "C.CFTV-01", "tipo": "passagem"})
    assert e.value.status_code == 400 and "Ja existe outro ponto" in e.value.detail
    meta = json.loads((camada_kmz / "c1.meta.json").read_text(encoding="utf-8"))
    assert meta["caixas"][cx2["id"]]["nome"] == "C.CFTV-03" and meta["caixas"][cx2["id"]]["ponto"] == "C.CFTV-03"
    assert _nomes(camada_kmz) == ["C.CFTV-01", "C.CFTV-03", "CTO-07"]


def test_caixa_nao_aponta_para_ponto_de_outro_lugar_nem_fica_em_cima_de_outra(camada_kmz):
    """O caso da C.CFTV-16 (22/10): a caixa passou a dizer que era um ponto de
    ~100 m dali e sumiu; depois uma caixa nova nasceu em cima dela."""
    r = tools._caixa_da_camada("c1", {"ponto": "C.CFTV-02", "nome": "C.CFTV-02", "tipo": "passagem", "lat": -10.001, "lng": -36.001})
    cx2 = next(iter(r["caixas"].values()))
    with pytest.raises(HTTPException) as e:   # C.CFTV-01 existe, mas em outro lugar
        tools._caixa_da_camada("c1", {"id": cx2["id"], "ponto": "C.CFTV-01", "nome": "C.CFTV-01", "tipo": "passagem",
                                      "lat": -10.001, "lng": -36.001})
    assert "nao esta neste lugar" in e.value.detail
    with pytest.raises(HTTPException) as e:   # caixa nova no mesmo lugar de outra
        tools._caixa_da_camada("c1", {"ponto": "C.CFTV-15", "nome": "C.CFTV-15", "tipo": "passagem", "lat": -10.001, "lng": -36.001})
    assert "Ja existe a caixa" in e.value.detail
    meta = json.loads((camada_kmz / "c1.meta.json").read_text(encoding="utf-8"))
    assert list(meta["caixas"]) == [cx2["id"]] and meta["caixas"][cx2["id"]]["ponto"] == "C.CFTV-02"


def test_renomear_cto_leva_os_cabos(camada_kmz):
    cx = next(iter(tools._caixa_da_camada("c1", {"ponto": "C.CFTV-01", "nome": "C.CFTV-01", "tipo": "onu", "portas": 4,
                                                 "lat": -10.0, "lng": -36.0})["caixas"].values()))
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "cto": {"ponto": "CTO-07", "porta": 2}, "tipo": "drop", "caminho": _CAMINHO})
    r = tools._cto_da_camada("c1", {"ponto": "CTO-07", "nome": "CTO VERDE 01", "lat": -10.002, "lng": -36.002, "splitter": "1:8"})
    assert r["aviso"] == "" and next(iter(r["ctos"].values()))["ponto"] == "CTO VERDE 01"
    assert next(iter(r["cabos"].values()))["cto"]["ponto"] == "CTO VERDE 01"
    assert "CTO VERDE 01" in _nomes(camada_kmz)


def test_renomear_ponto_no_editor_leva_a_caixa(camada_kmz):
    cx = next(iter(tools._caixa_da_camada("c1", {"ponto": "C.CFTV-01", "nome": "C.CFTV-01", "tipo": "passagem",
                                                 "lat": -10.0, "lng": -36.0})["caixas"].values()))
    tools._editar_ponto_da_camada("c1", {"nome": "C.CFTV-01", "novo_nome": "CX-ENTRADA", "lat_atual": -10.0, "lon_atual": -36.0})
    meta = json.loads((camada_kmz / "c1.meta.json").read_text(encoding="utf-8"))
    assert meta["caixas"][cx["id"]]["ponto"] == "CX-ENTRADA"


def test_nome_repetido_renomeia_so_o_ponto_da_caixa(tmp_path, monkeypatch):
    """Porto Real tem 14 "Caixa - S 4P": renomear uma caixa mexe so no ponto dela."""
    import zipfile
    from app.services.kmz_ops import kmz_to_geojson
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "_apagar_geradas_do_mapa", lambda *a, **k: None)
    pts = [("Caixa - S 4P", -10.0 - i * 0.001, -36.0) for i in range(14)]
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           + "".join(f"<Placemark><name>{n}</name><Point><coordinates>{lo},{la},0</coordinates></Point></Placemark>" for n, la, lo in pts)
           + "</Document></kml>")
    with zipfile.ZipFile(tmp_path / "c1.kmz", "w") as zf:
        zf.writestr("doc.kml", kml)
    (tmp_path / "c1.geojson").write_text(json.dumps(kmz_to_geojson(tmp_path / "c1.kmz")), encoding="utf-8")
    (tmp_path / "c1.meta.json").write_text(json.dumps({"id": "c1"}), encoding="utf-8")
    a = next(iter(tools._caixa_da_camada("c1", {"ponto": "Caixa - S 4P", "nome": "Caixa - S 4P", "tipo": "passagem",
                                                "lat": -10.003, "lng": -36.0})["caixas"].values()))
    tools._caixa_da_camada("c1", {"ponto": "Caixa - S 4P", "nome": "Caixa - S 4P", "tipo": "passagem", "lat": -10.005, "lng": -36.0})
    r = tools._caixa_da_camada("c1", {"id": a["id"], "ponto": "Caixa - S 4P", "nome": "C.CFTV-09", "tipo": "passagem"})
    assert r["aviso"] == ""
    nomes = _nomes(tmp_path)
    assert nomes.count("Caixa - S 4P") == 13 and nomes.count("C.CFTV-09") == 1
    feat = next(f for f in json.loads((tmp_path / "c1.geojson").read_text(encoding="utf-8"))["features"] if f["properties"]["name"] == "C.CFTV-09")
    assert abs(feat["geometry"]["coordinates"][1] - -10.003) < 1e-6
    caixas = r["caixas"]
    assert caixas[a["id"]]["ponto"] == "C.CFTV-09"
    assert [c["ponto"] for k, c in caixas.items() if k != a["id"]] == ["Caixa - S 4P"]  # a outra nao foi junto


def test_arrastar_ponto_leva_caixa_cto_e_pontas_dos_cabos(camada_kmz):
    """Arrastar no editor: CTO-07, a caixa C.CFTV-01 e a camera (C.CFTV-02 faz
    de camera aqui) -- cada cabo acompanha so pela ponta que e dele."""
    cx = next(iter(tools._caixa_da_camada("c1", {"ponto": "C.CFTV-01", "nome": "C.CFTV-01", "tipo": "switch", "portas": 4,
                                                 "lat": -10.0, "lng": -36.0})["caixas"].values()))
    tools._cto_da_camada("c1", {"ponto": "CTO-07", "nome": "CTO-07", "lat": -10.002, "lng": -36.002, "splitter": "1:8"})
    drop = [[-10.0, -36.0], [-10.001, -36.0015], [-10.002, -36.002]]
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "cto": {"ponto": "CTO-07", "porta": 1}, "tipo": "drop", "caminho": drop})
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "porta": 1, "camera": {"ponto": "C.CFTV-02", "ip": "10.0.0.9"},
                                 "tipo": "utp5e", "caminho": [[-10.0, -36.0], [-10.001, -36.001]]})

    def cabos():
        meta = json.loads((camada_kmz / "c1.meta.json").read_text(encoding="utf-8"))
        por = {("cto" if c.get("cto") else "cam"): c for c in meta["cabos"].values()}
        return meta, por

    tools._editar_ponto_da_camada("c1", {"nome": "CTO-07", "lat": -10.003, "lon": -36.003, "lat_atual": -10.002, "lon_atual": -36.002})
    meta, por = cabos()
    assert por["cto"]["caminho"][-1] == [-10.003, -36.003] and por["cto"]["caminho"][0] == [-10.0, -36.0]
    assert next(iter(meta["ctos"].values()))["lat"] == -10.003
    assert por["cam"]["caminho"] == [[-10.0, -36.0], [-10.001, -36.001]]          # cabo da camera nao mexeu

    tools._editar_ponto_da_camada("c1", {"nome": "C.CFTV-01", "lat": -9.9995, "lon": -35.9995, "lat_atual": -10.0, "lon_atual": -36.0})
    meta, por = cabos()
    assert meta["caixas"][cx["id"]]["lat"] == -9.9995                              # a caixa nao perde o ponto
    assert por["cto"]["caminho"][0] == [-9.9995, -35.9995] and por["cam"]["caminho"][0] == [-9.9995, -35.9995]
    assert por["cto"]["caminho"][-1] == [-10.003, -36.003]

    tools._editar_ponto_da_camada("c1", {"nome": "C.CFTV-02", "lat": -10.0012, "lon": -36.0012, "lat_atual": -10.001, "lon_atual": -36.001})
    meta, por = cabos()
    assert por["cam"]["caminho"][-1] == [-10.0012, -36.0012] and por["cam"]["metros"] > 0
