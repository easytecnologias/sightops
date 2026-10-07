"""Ativacao de TR-069: endereco do servidor, opcao 43, script do MikroTik e OLT."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.cli.tools.olt_fiberhome import parse_rmt_manage
from app.services import tr069_ativacao as ativ

FH = Path(__file__).parent / "fixtures" / "fiberhome_an5516"


def test_opcao_43_igual_a_do_mikrotik_da_sierra():
    # Valor que esta em /ip dhcp-server option do RT-SIERRA e que a 140PoE leu.
    assert ativ.opcao_43_hex("http://10.201.0.26:7547") == "0x0117687474703a2f2f31302e3230312e302e32363a37353437"


def test_url_do_servidor_pelo_iso_index(monkeypatch):
    import app.services.connector_service as cs
    monkeypatch.setattr(cs, "get_connector", lambda cid, enforce_tenant=False: {"name": "SIERRA", "iso_index": 13})
    assert ativ.url_do_servidor("1d634b442abbac6c") == "http://10.201.0.26:7547"


def test_conector_sem_tunel_isolado_e_recusado(monkeypatch):
    import app.services.connector_service as cs
    monkeypatch.setattr(cs, "get_connector", lambda cid, enforce_tenant=False: {"name": "VELHO", "iso_index": None})
    with pytest.raises(ativ.AtivacaoError, match="tunel isolado"):
        ativ.url_do_servidor("x")


def test_conector_de_outro_cliente_e_recusado(monkeypatch):
    import app.services.connector_service as cs
    monkeypatch.setattr(cs, "get_connector", lambda cid, enforce_tenant=False: None)
    with pytest.raises(ativ.AtivacaoError, match="conector deste cliente"):
        ativ.url_do_servidor("alheio")


def test_script_mikrotik():
    s = ativ.script_mikrotik("http://10.201.0.26:7547", "172.18.1.0/24")
    assert 'code=43 value=0x0117687474703a2f2f31302e3230312e302e32363a37353437' in s
    assert 'address="172.18.1.0/24"' in s
    assert "src-address=172.18.1.0/24 dst-address=10.201.0.26 protocol=tcp dst-port=7547 action=masquerade" in s
    # nao apaga as outras opcoes de DHCP da rede: so acrescenta
    assert 'dhcp-option=($opcoes, "sightops-acs")' in s
    with pytest.raises(ativ.AtivacaoError):
        ativ.script_mikrotik("http://10.201.0.26:7547", "172.18.1.0")


def test_parse_rmt_manage_real_desligado():
    out = (FH / "rmt_manage_4_6_89_desligado.txt").read_text(encoding="utf-8")
    assert parse_rmt_manage(out) == {"tr069": False, "acs_url": "", "intervalo": 0}


def test_parse_rmt_manage_ligado():
    out = "TR069 Enable/Disable:enable\r\nACL Url:http://10.201.0.26:7547\r\nInform Interval:300\r\n"
    assert parse_rmt_manage(out) == {"tr069": True, "acs_url": "http://10.201.0.26:7547", "intervalo": 300}
