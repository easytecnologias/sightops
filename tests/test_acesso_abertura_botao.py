"""Passagem aberta pelo botao (Method 5) ou remotamente (Method 4) sem pessoa:
o leitor nao identifica ninguem, entao nao conta como "So no leitor"."""
from app.services.access_control_store import tipo_de_abertura


def _ev(method, user_id="", person_id=""):
    return {"person_id": person_id,
            "raw_payload": '{"method": "%s", "user_id": "%s", "event_type": "entrada"}' % (method, user_id)}


def test_botao_e_remota_sem_pessoa():
    assert tipo_de_abertura(_ev("5")) == "botao"
    assert tipo_de_abertura(_ev("4", "SightOps")) == "remota"


def test_rosto_e_pessoa_cadastrada_nao_sao_abertura():
    assert tipo_de_abertura(_ev("15", "3921")) == ""              # rosto
    assert tipo_de_abertura(_ev("5", "", person_id="abc")) == ""  # tem pessoa
    assert tipo_de_abertura(_ev("5", "1023")) == ""               # botao com usuario
    assert tipo_de_abertura({"person_id": "", "raw_payload": "nao e json"}) == ""
    assert tipo_de_abertura({"person_id": "", "raw_payload": ""}) == ""
