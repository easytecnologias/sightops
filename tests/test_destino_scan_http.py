"""/api/scan e /api/rescan-single-ip passam pela regra de destino antes do
subprocesso, que grava inventario e tenta senha padrao."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models.requests import RescanSingleIPRequest, ScanRequest
from app.services import rescan_service as R
from app.services import scan_service as S
from test_destino_permitido import rede  # noqa: F401  (fixture)


@pytest.fixture
def sem_subprocesso(rede, monkeypatch):
    chamadas = []

    def _run(cmd, **kw):
        chamadas.append(cmd)
        raise RuntimeError("parou aqui")

    monkeypatch.setattr(S.subprocess, "run", _run)
    return chamadas


@pytest.mark.parametrize("alvo", ["10.208.1.5", "127.0.0.1", "10.99.0.0/24"])
def test_scan_http_recusa_antes_do_subprocesso(sem_subprocesso, alvo):
    with pytest.raises(HTTPException) as exc:
        S.run_http_scan(ScanRequest(alvo=alvo))
    assert exc.value.status_code == 403
    assert sem_subprocesso == []


def test_scan_http_da_lan_do_cliente_segue(sem_subprocesso):
    with pytest.raises(RuntimeError):
        S.run_http_scan(ScanRequest(alvo="192.168.10.0/28"))
    assert len(sem_subprocesso) == 1


def test_rescan_recusa_antes_do_subprocesso(sem_subprocesso):
    with pytest.raises(HTTPException) as exc:
        R.rescan_single_ip(RescanSingleIPRequest(ip="10.208.1.5"))
    assert exc.value.status_code == 403
    assert sem_subprocesso == []
