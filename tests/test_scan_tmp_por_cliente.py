"""Arquivo temporario da varredura fica na pasta do cliente, com nome unico."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import tenant_context as TC
from app.models.requests import RescanSingleIPRequest, ScanRequest
from app.services import rescan_service as R
from app.services import scan_service as S
from test_destino_permitido import rede  # noqa: F401  (fixture)


@pytest.fixture
def saidas(rede, monkeypatch, tmp_path):
    monkeypatch.setattr(TC, "DATA_DIR", tmp_path)
    caminhos = []

    def _run(cmd, **kw):
        destino = cmd[cmd.index("--out") + 1]
        caminhos.append(destino)
        open(destino, "w", encoding="utf-8").write("[]")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(S.subprocess, "run", _run)
    return caminhos


def _pasta(caminhos, tmp_path):
    return [str(tmp_path / "tenants" / "cliente-a") in c.replace("/", "\\") or
            str(tmp_path / "tenants" / "cliente-a").replace("\\", "/") in c for c in caminhos]


@pytest.mark.parametrize("linhas_antigas", [[], [{"ip": "192.168.10.1"}]])
def test_scan_grava_o_temporario_na_pasta_do_cliente(saidas, monkeypatch, tmp_path, linhas_antigas):
    monkeypatch.setattr(S, "load_inventory_json", lambda mode="olt": list(linhas_antigas))

    def _para(rows, mode="olt"):
        raise RuntimeError("parou aqui")

    monkeypatch.setattr(S, "save_inventory_json", _para)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            S.run_http_scan(ScanRequest(alvo="192.168.10.0/30"))
    assert all(_pasta(saidas, tmp_path))
    assert len(set(saidas)) == 2
    assert not list((tmp_path / "tenants" / "cliente-a").glob("*.tmp.json"))  # apagados


def test_rescan_grava_o_temporario_na_pasta_do_cliente(saidas, monkeypatch, tmp_path):
    monkeypatch.setattr(R, "load_inventory_json", lambda mode="olt": [])
    R.rescan_single_ip(RescanSingleIPRequest(ip="192.168.10.5"))
    assert all(_pasta(saidas, tmp_path))
    assert not list((tmp_path / "tenants" / "cliente-a").glob("*.tmp.json"))
