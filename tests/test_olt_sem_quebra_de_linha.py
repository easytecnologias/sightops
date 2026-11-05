"""R3: quebra de linha em descricao/serial/profile nao vira comando na OLT."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.cli.tools import olt_8820i_add_onu as T
from app.models.requests import OltAddOnuRequest, OltFindOnuRequest, OltRegistryRequest


@pytest.mark.parametrize("campo", ["description", "serial", "profile"])
def test_modelo_recusa_quebra_de_linha(campo):
    base = {"pon": 1, "serno_id": 1, "vlan": 10}
    with pytest.raises(ValidationError):
        OltAddOnuRequest(**base, **{campo: "camera 1\nonu delete gpon 1 onu 2"})
    with pytest.raises(ValidationError):
        OltAddOnuRequest(**base, **{campo: "x\r"})
    assert getattr(OltAddOnuRequest(**base, **{campo: "camera 1"}), campo) == "camera 1"


def test_serial_da_busca_e_cadastro():
    with pytest.raises(ValidationError):
        OltFindOnuRequest(serial="ITBS1234\nreboot")
    with pytest.raises(ValidationError):
        OltRegistryRequest(name="OLT", host="10.0.0.1", username="admin\nconfig")
    assert OltRegistryRequest(name="OLT", host="10.0.0.1", notes="linha 1\nlinha 2").notes


class _Canal:
    def __init__(self):
        self.enviado = []

    def recv_ready(self):
        return False

    def send(self, dado):
        self.enviado.append(dado)


def test_cli_run_recusa_quebra_de_linha_sem_enviar():
    canal = _Canal()
    with pytest.raises(ValueError):
        T.cli_run(canal, "onu description add gpon 1 onu 1 text a\nonu delete gpon 1 onu 1")
    with pytest.raises(ValueError):
        T.cli_run_with_confirmation(canal, "onu delete gpon 1 onu 1\r\ny", ["y"])
    assert canal.enviado == []
