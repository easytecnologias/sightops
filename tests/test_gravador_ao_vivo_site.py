"""Ao vivo de gravador respeita o site do usuario, como a gravacao (/api/nvr/driver/*)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.endpoints import deployments as D
from app.api.endpoints import recorder_driver as R


def test_gravador_de_site_nao_liberado_nao_abre_ao_vivo(monkeypatch):
    monkeypatch.setattr(R, "_host_liberado", lambda host: False)
    chamou = []
    monkeypatch.setattr(D, "_credencial_gravador", lambda *a, **k: chamou.append(1) or ("admin", "x"))
    with pytest.raises(HTTPException) as exc:
        D.api_deployments_recorder_live_stream({"recorder_host": "192.168.24.227", "canal": 3})
    assert exc.value.status_code == 403
    assert chamou == []  # nem chega a buscar a senha do gravador


def test_sem_restricao_segue_o_caminho_de_sempre(monkeypatch):
    monkeypatch.setattr(R, "_host_liberado", lambda host: True)
    monkeypatch.setattr(D, "_credencial_gravador", lambda *a, **k: ("admin", ""))
    with pytest.raises(HTTPException) as exc:
        D.api_deployments_recorder_live_stream({"recorder_host": "192.168.24.227", "canal": 3})
    assert exc.value.status_code == 428  # sem senha guardada: o mesmo de antes
