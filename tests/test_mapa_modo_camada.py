"""Mapa: modo (OLT/Switch/Basico/todos) gravado no meta da camada KMZ."""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.api.endpoints import tools


def test_modo_da_camada(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path)
    (tmp_path / "c1.kmz").write_bytes(b"kmz")
    (tmp_path / "c1.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    (tmp_path / "c1.meta.json").write_text(json.dumps({"id": "c1", "label": "PORTO REAL"}), encoding="utf-8")
    tools._modo_da_camada("c1", "Switch")
    meta = json.loads((tmp_path / "c1.meta.json").read_text(encoding="utf-8"))
    assert meta["modo"] == "switch" and meta["label"] == "PORTO REAL"  # nao perde o resto do meta
    tools._modo_da_camada("c1", "")  # volta ao automatico
    assert json.loads((tmp_path / "c1.meta.json").read_text(encoding="utf-8"))["modo"] == ""
    with pytest.raises(HTTPException):
        tools._modo_da_camada("c1", "dvr")
    with pytest.raises(HTTPException):
        tools._modo_da_camada("nao-existe", "olt")
