"""Mapa: rack da rede neutra (DIO, OLT, borda, switch, gravadores...). Dados ficticios.

O usuario monta o rack e liga porta a porta; o registro fica no meta da
camada como a CDO, e o caminho de uma porta segue as ligacoes."""
from __future__ import annotations

import json
import zipfile

import pytest
from fastapi import HTTPException

from app.api.endpoints import tools
from app.services import mapa_rack as R
from app.services.kmz_ops import kmz_to_geojson

PTS = [("RACK DATACENTER", -10.0, -36.0), ("CDO-01", -10.001, -36.001)]


def _portas(prefixo, n, inicio=1):
    return [{"id": f"{prefixo}{i}"} for i in range(inicio, inicio + n)]


def _equipamentos():
    return [
        {"id": "dio", "tipo": "dio", "nome": "DIO PROVEDORES", "portas": _portas("P", 12)},
        {"id": "crs", "tipo": "switch", "nome": "SWITCH JARDINS", "modelo": "CRS317-1G-16S+",
         "portas": [{"id": "ether1"}] + _portas("sfp-sfpplus", 16)},
        {"id": "olt", "tipo": "olt", "nome": "OLT JARDINS I", "entidade": "olt:jardins", "portas": _portas("PON", 8) + _portas("UP", 2)},
        {"id": "ccr", "tipo": "borda", "nome": "CCR BORDA", "portas": _portas("ether", 8) + _portas("sfp-sfpplus", 2)},
    ]


@pytest.fixture()
def camada(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path)
    monkeypatch.setattr(tools, "_apagar_geradas_do_mapa", lambda *a, **k: None)
    admin = {"pode": True}

    def _exige():
        if not admin["pode"]:
            raise HTTPException(403, "so admin")
    monkeypatch.setattr(tools, "_exige_admin_para_excluir", _exige)
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           + "".join(f"<Placemark><name>{n}</name><Point><coordinates>{lo},{la},0</coordinates></Point></Placemark>" for n, la, lo in PTS)
           + "</Document></kml>")
    with zipfile.ZipFile(tmp_path / "c1.kmz", "w") as zf:
        zf.writestr("doc.kml", kml)
    (tmp_path / "c1.geojson").write_text(json.dumps(kmz_to_geojson(tmp_path / "c1.kmz")), encoding="utf-8")
    (tmp_path / "c1.meta.json").write_text(json.dumps({"id": "c1", "label": "PERUCABA"}), encoding="utf-8")
    return admin


def _criar(**extra):
    dados = {"ponto": "RACK DATACENTER", "lat": -10.0, "lng": -36.0, "equipamentos": _equipamentos()}
    dados.update(extra)
    r = tools._rack_da_camada("c1", dados)
    return r["racks"][r["rack_id"]]


def test_rack_com_equipamentos_e_ligacoes(camada):
    rack = _criar(ligacoes=[
        {"id": "l1", "a": {"eq": "dio", "porta": "P3"}, "b": {"eq": "crs", "porta": "sfp-sfpplus4"}, "tipo": "patch"},
        {"id": "l2", "a": {"eq": "crs", "porta": "SFP-SFPPLUS7"}, "b": {"eq": "olt", "porta": "UP1"}, "tipo": "dac"},
    ], provedores=[{"nome": "VOE TELECOM", "entrada": {"eq": "crs", "porta": "sfp-sfpplus4"}, "vlans": "3030, 3031"}])
    assert [e["nome"] for e in rack["equipamentos"]] == ["DIO PROVEDORES", "SWITCH JARDINS", "OLT JARDINS I", "CCR BORDA"]
    assert rack["ligacoes"][1]["a"]["porta"] == "sfp-sfpplus7"   # grafia da porta como cadastrada
    assert rack["provedores"][0]["vlans"] == [3030, 3031]
    caminho = R.caminho_da_porta(rack, "dio", "P3")
    assert [(c["nome"], c["porta"]) for c in caminho] == [("DIO PROVEDORES", "P3"), ("SWITCH JARDINS", "sfp-sfpplus4")]


def test_porta_so_tem_uma_ligacao_e_tem_que_existir(camada):
    with pytest.raises(HTTPException, match="ja esta ligada|já está ligada"):
        _criar(ligacoes=[
            {"a": {"eq": "dio", "porta": "P1"}, "b": {"eq": "crs", "porta": "sfp-sfpplus1"}},
            {"a": {"eq": "dio", "porta": "P2"}, "b": {"eq": "crs", "porta": "sfp-sfpplus1"}},
        ])
    with pytest.raises(HTTPException, match="não tem a porta"):
        _criar(ligacoes=[{"a": {"eq": "dio", "porta": "P99"}, "b": {"eq": "crs", "porta": "sfp-sfpplus1"}}])
    with pytest.raises(HTTPException, match="não está neste rack"):
        _criar(ligacoes=[{"a": {"eq": "outro", "porta": "P1"}, "b": {"eq": "crs", "porta": "sfp-sfpplus1"}}])


def test_validacoes(camada):
    with pytest.raises(HTTPException):
        _criar(equipamentos=[{"tipo": "dio", "nome": "SEM PORTAS", "portas": []}])
    with pytest.raises(HTTPException):
        _criar(equipamentos=[{"tipo": "geladeira", "nome": "X", "portas": _portas("P", 1)}])
    with pytest.raises(HTTPException):
        _criar(equipamentos=[{"tipo": "dio", "nome": "X", "portas": [{"id": "P1"}, {"id": "p1"}]}])
    with pytest.raises(HTTPException, match="VLAN"):
        _criar(provedores=[{"nome": "X", "entrada": {"eq": "crs", "porta": "ether1"}, "vlans": "5000"}])
    assert R._vlans("2500-2502, 7") == [7, 2500, 2501, 2502]
    _criar()
    with pytest.raises(HTTPException, match="Já existe um rack"):
        tools._rack_da_camada("c1", {"ponto": "OUTRO", "lat": -10.0, "lng": -36.0})


def test_editar_so_o_nome_mantem_o_que_tem_dentro(camada):
    rack = _criar(ligacoes=[{"id": "l1", "a": {"eq": "dio", "porta": "P1"}, "b": {"eq": "crs", "porta": "sfp-sfpplus1"}}])
    r = tools._rack_da_camada("c1", {"id": rack["id"], "obs": "sala do datacenter"})
    novo = r["racks"][rack["id"]]
    assert len(novo["equipamentos"]) == 4 and len(novo["ligacoes"]) == 1 and novo["obs"] == "sala do datacenter"


def test_operador_liga_mas_nao_desfaz(camada):
    rack = _criar(ligacoes=[{"id": "l1", "a": {"eq": "dio", "porta": "P1"}, "b": {"eq": "crs", "porta": "sfp-sfpplus1"}}])
    camada["pode"] = False
    # acrescentar ligacao: pode
    tools._rack_da_camada("c1", {"id": rack["id"], "ligacoes": rack["ligacoes"] + [
        {"id": "l2", "a": {"eq": "dio", "porta": "P2"}, "b": {"eq": "crs", "porta": "sfp-sfpplus2"}}]})
    # desfazer, trocar a ponta, tirar equipamento ou excluir o rack: so admin
    with pytest.raises(HTTPException, match="so admin"):
        tools._rack_da_camada("c1", {"id": rack["id"], "ligacoes": []})
    with pytest.raises(HTTPException, match="so admin"):
        tools._rack_da_camada("c1", {"id": rack["id"], "ligacoes": [
            {"id": "l1", "a": {"eq": "dio", "porta": "P5"}, "b": {"eq": "crs", "porta": "sfp-sfpplus1"}}]})
    with pytest.raises(HTTPException, match="so admin"):
        tools._rack_da_camada("c1", {"id": rack["id"], "equipamentos": _equipamentos()[:3]})
    with pytest.raises(HTTPException, match="so admin"):
        tools._rack_da_camada("c1", {"id": rack["id"], "excluir": True})
    camada["pode"] = True
    r = tools._rack_da_camada("c1", {"id": rack["id"], "excluir": True})
    assert r["racks"] == {}


def test_rack_aparece_na_lista_e_acompanha_o_ponto(camada, tmp_path):
    rack = _criar()
    meta = json.loads((tmp_path / "c1.meta.json").read_text(encoding="utf-8"))
    assert rack["id"] in meta["racks"]
    n = tools._arrastar_ponto_no_meta(meta, "RACK DATACENTER", (-10.0, -36.0), (-10.0005, -36.0005))
    assert n == 0 and meta["racks"][rack["id"]]["lat"] == -10.0005
    tools._trocar_nome_do_ponto_no_meta(meta, "RACK DATACENTER", "RACK JARDINS", (-10.0005, -36.0005), True)
    assert meta["racks"][rack["id"]]["ponto"] == "RACK JARDINS"
    assert set(tools._rede_da_camada(meta)) >= {"racks", "cdos"}
