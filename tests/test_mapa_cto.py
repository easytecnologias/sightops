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
