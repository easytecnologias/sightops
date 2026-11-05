"""R2: operacao de OLT sem olt_id nao vai para IP/senha/conector vindos do
navegador. So OLT cadastrada no cliente atual; olt_id de outro cliente da 404."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.endpoints import olt as E
from app.models.requests import OltOnuSignalRequest
from app.services import olt_registry

OLTS_DO_CLIENTE = [{"id": 7, "host": "10.0.0.2", "connector_id": "conn-a"}]


@pytest.fixture
def registro(monkeypatch):
    monkeypatch.setattr(olt_registry, "list_olts", lambda include_inactive=True: list(OLTS_DO_CLIENTE))

    def _credenciais(olt_id):
        if int(olt_id) != 7:
            raise olt_registry.OltNotFound(f"OLT {olt_id} nao encontrada neste tenant")
        return {"id": 7, "host": "10.0.0.2", "username": "admin", "password": "cadastrada",
                "connector_id": "", "active": True, "name": "OLT A", "site": "", "model": "", "vendor": ""}

    monkeypatch.setattr(olt_registry, "resolve_credentials", _credenciais)


def _req(**kw):
    base = {"olt_ip": "10.0.0.2", "user": "x", "password": "digitada", "pon": 1, "onu": 1}
    base.update(kw)
    return OltOnuSignalRequest(**base)


def test_sem_olt_id_e_ip_fora_do_cliente_da_400(registro):
    with pytest.raises(HTTPException) as exc:
        E._registered_request(_req(olt_ip="10.209.0.2"))
    assert exc.value.status_code == 400


def test_sem_olt_id_usa_a_olt_cadastrada_do_cliente(registro):
    req = E._registered_request(_req())
    assert req.olt_ip == "10.0.0.2" and req.password == "cadastrada"


def test_olt_id_de_outro_cliente_da_404(registro):
    with pytest.raises(HTTPException) as exc:
        E._registered_request(_req(olt_id=99))
    assert exc.value.status_code == 404
