"""Hikvision com firmware novo responde em isapi.org -- e tem que ser lido igual."""
from __future__ import annotations

import pytest

from app.services import hik_xml

# Trecho real do DS-7732NXI-I4/S V5.04.066 (Mega Alarmes, 14/10/2026).
DEVICE_INFO_NOVO = (
    '<?xml version="1.0" encoding="UTF-8" ?>'
    '<DeviceInfo version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
    '<deviceName>AcuSense</deviceName><model>DS-7732NXI-I4/S</model>'
    '<serialNumber>DS-7732NXI-I4/S-1620250715CCRRGC9701789WCVU</serialNumber>'
    '<firmwareVersion>V5.04.066</firmwareVersion></DeviceInfo>'
)
DEVICE_INFO_ANTIGO = DEVICE_INFO_NOVO.replace("www.isapi.org", "www.hikvision.com")


@pytest.mark.parametrize("xml", [DEVICE_INFO_NOVO, DEVICE_INFO_ANTIGO])
def test_os_dois_namespaces_sao_lidos(xml):
    raiz = hik_xml.ler(xml)
    assert raiz.findtext("h:model", "", hik_xml.NS) == "DS-7732NXI-I4/S"


def test_lixo_nao_e_xml():
    assert hik_xml.ler("") is None and hik_xml.ler("<html>401") is None


def test_raio_x_hikvision_firmware_novo(monkeypatch):
    from app.services import recorder_xray as X
    canais = (
        '<InputProxyChannelList version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema" size="1">'
        '<InputProxyChannel><id>1</id><name>PORTARIA</name><sourceInputPortDescriptor>'
        '<proxyProtocol>HIKVISION</proxyProtocol><ipAddress>192.168.18.51</ipAddress>'
        '<managePortNo>8000</managePortNo></sourceInputPortDescriptor></InputProxyChannel>'
        '</InputProxyChannelList>'
    )

    def pedir(url, user, password, timeout=0):
        if url.endswith("/ISAPI/System/deviceInfo"):
            return 200, DEVICE_INFO_NOVO
        if url.endswith("/ISAPI/ContentMgmt/InputProxy/channels"):
            return 200, canais
        return 404, ""
    monkeypatch.setattr(X, "_pedir", pedir)
    d = X._xray_hikvision("http://x", "admin", "x")
    assert d["equipamento"]["modelo"] == "DS-7732NXI-I4/S"  # antes: "" -> "confira usuario e senha"
    assert any(str(c.get("ip")) == "192.168.18.51" for c in d["canais"])


def test_indice_da_investigacao_firmware_novo():
    from app.services.recorder_driver import parse_indice_hik
    xml = (
        '<CMSearchResult version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
        '<responseStatusStrg>OK</responseStatusStrg><matchList><searchMatchItem>'
        '<timeSpan><startTime>2026-10-14T12:00:00Z</startTime><endTime>2026-10-14T12:05:00Z</endTime></timeSpan>'
        '</searchMatchItem></matchList></CMSearchResult>'
    )
    segs, status = parse_indice_hik(xml)
    assert status == "OK" and len(segs) == 1  # antes: zero trechos, calado


def test_erro_de_escrita_nao_vira_sucesso():
    from app.services.recorder_write import _hik_erro
    xml = ('<ResponseStatus version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
           '<statusString>Invalid Content</statusString><subStatusCode>badParameters</subStatusCode>'
           '</ResponseStatus>')
    assert _hik_erro(xml) == "Invalid Content · badParameters"
    assert _hik_erro(xml.replace("Invalid Content", "OK")) == ""


def test_raio_x_recusa_ip_fora_das_redes_do_conector(monkeypatch):
    from app.services import recorder_xray as X
    monkeypatch.setattr(X._vnat, "has_mapping", lambda cid: True)
    monkeypatch.setattr(X._vnat, "virtual_ip_for", lambda cid, ip: ip)  # fora do mapa: IP real

    def nao_pode(*a, **k):
        raise AssertionError("nao podia ter ido ao IP real")
    monkeypatch.setattr(X, "detectar_marca", nao_pode)
    with pytest.raises(ValueError, match="nao esta nas redes deste conector"):
        X.raio_x("192.168.18.80", "admin", "x", 80, "4fef0f33b137a51e")
