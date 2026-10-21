"""Mapa: caixa de CFTV (o que tem dentro, portas) e cabo caixa -> camera
gravados no meta da camada KMZ. Dados ficticios."""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.api.endpoints import tools
from app.core import tenant_context as T


@pytest.fixture()
def camada(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path)
    (tmp_path / "c1.kmz").write_bytes(b"kmz")
    (tmp_path / "c1.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    (tmp_path / "c1.meta.json").write_text(json.dumps({"id": "c1", "label": "PORTO REAL", "cor_outros": "#123456"}), encoding="utf-8")
    return tmp_path


def _como(role):
    return T.set_current_user({"id": 9, "username": "u", "role": role, "tenant_slug": "x", "effective_tenant_slug": "x"})


def _caixa(**kw):
    base = {"ponto": "CAI", "nome": "CAI-01", "portas": 8,
            "itens": [{"tipo": "switch_poe", "modelo": "SG 800", "qtd": 1}, {"tipo": "onu", "modelo": "", "qtd": 1}]}
    base.update(kw)
    r = tools._caixa_da_camada("c1", base, "op")
    return next(iter(r["caixas"].values())) if "id" not in kw else r["caixas"][kw["id"]]


# dois pontos ~100 m um do outro (0,0009 grau de latitude)
_CAMINHO = [[-10.0, -36.0], [-10.0009, -36.0]]


def test_caixa_e_cabo(camada):
    cx = _caixa()
    assert cx["nome"] == "CAI-01" and cx["portas"] == 8 and [i["tipo"] for i in cx["itens"]] == ["switch_poe", "onu"]
    r = tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "14", "ip": "10.45.0.246"}, "tipo": "utp5e",
                                     "porta": 1, "folga_pct": 10, "caminho": _CAMINHO}, "op")
    cabo = next(iter(r["cabos"].values()))
    assert 99 <= cabo["metros"] <= 101 and cabo["metros_com_folga"] == round(cabo["metros"] * 1.1, 1)
    meta = json.loads((camada / "c1.meta.json").read_text(encoding="utf-8"))
    assert meta["cor_outros"] == "#123456" and cx["id"] in meta["caixas"]  # nao perde o resto do meta
    # a mesma camera nao ganha segundo cabo
    with pytest.raises(HTTPException) as e:
        tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "14", "ip": "10.45.0.246"}, "porta": 3, "caminho": _CAMINHO})
    assert "ja tem cabo" in e.value.detail and "porta 1" in e.value.detail
    # porta ocupada
    with pytest.raises(HTTPException) as e:
        tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "15"}, "porta": 1, "caminho": _CAMINHO})
    assert "ja tem cabo" in e.value.detail
    # porta alem do switch
    with pytest.raises(HTTPException):
        tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "15"}, "porta": 9, "caminho": _CAMINHO})
    # switch nao encolhe abaixo da porta usada
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "16"}, "porta": 6, "caminho": _CAMINHO})
    with pytest.raises(HTTPException):
        _caixa(id=cx["id"], portas=4)


def test_validacoes(camada):
    with pytest.raises(HTTPException):
        tools._caixa_da_camada("c1", {"ponto": ""})
    with pytest.raises(HTTPException):
        tools._caixa_da_camada("c1", {"ponto": "CAI", "itens": [{"tipo": "geladeira"}]})
    cx = _caixa()
    with pytest.raises(HTTPException):
        tools._caixa_da_camada("c1", {"ponto": "cai"})  # mesmo ponto, outra caixa
    for ruim in ({"caminho": [[-10, -36]]}, {"caminho": [["x", 1], [1, 2]]}, {"caminho": _CAMINHO, "tipo": "laser"},
                 {"caminho": _CAMINHO, "camera": {}}):
        dados = {"caixa": cx["id"], "camera": {"ponto": "14"}, **ruim}
        with pytest.raises(HTTPException):
            tools._cabo_da_camada("c1", dados)
    with pytest.raises(HTTPException):
        tools._cabo_da_camada("c1", {"caixa": "outra", "camera": {"ponto": "14"}, "caminho": _CAMINHO})


def test_excluir_so_admin_e_caixa_leva_os_cabos(camada):
    cx = _caixa()
    r = tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "14"}, "porta": 2, "caminho": _CAMINHO})
    kid = next(iter(r["cabos"]))
    tok = _como("operator")
    try:
        with pytest.raises(HTTPException) as e:
            tools._cabo_da_camada("c1", {"id": kid, "excluir": True})
        assert e.value.status_code == 403
        with pytest.raises(HTTPException):
            tools._caixa_da_camada("c1", {"id": cx["id"], "excluir": True})
    finally:
        T.reset_current_user(tok)
    tok = _como("admin")
    try:
        r = tools._caixa_da_camada("c1", {"id": cx["id"], "excluir": True})
    finally:
        T.reset_current_user(tok)
    assert r["caixas"] == {} and r["cabos"] == {}


def test_trocar_camera_do_cabo_e_excluir(camada):
    cx = _caixa()
    r = tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "14", "ip": "10.45.0.14"}, "porta": 1, "caminho": _CAMINHO})
    kid = next(iter(r["cabos"]))
    # mudar so o tracado/porta do mesmo cabo: edicao normal
    tools._cabo_da_camada("c1", {"id": kid, "caixa": cx["id"], "camera": {"ponto": "14", "ip": "10.45.0.14"}, "porta": 2, "caminho": _CAMINHO})
    tok = _como("operator")
    try:
        with pytest.raises(HTTPException) as e:  # trocar a camera = excluir + criar
            tools._cabo_da_camada("c1", {"id": kid, "caixa": cx["id"], "camera": {"ponto": "17", "ip": "10.45.0.17"}, "caminho": _CAMINHO})
        assert e.value.status_code == 403
    finally:
        T.reset_current_user(tok)


def test_id_da_camada_saneado_no_meta(camada):
    tools._caixa_da_camada('c1.<img src=x onerror=alert(1)>', {"ponto": "CAI"})
    assert json.loads((camada / "c1.meta.json").read_text(encoding="utf-8"))["id"] == "c1"
