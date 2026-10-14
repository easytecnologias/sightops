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


# --- troca de IP de camera Hikvision (escreve na camera) ----------------------

REDE_NOVA = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<IPAddress version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
    '<ipVersion>v4</ipVersion><addressingType>dynamic</addressingType>'
    '<ipAddress>192.168.18.51</ipAddress><subnetMask>255.255.254.0</subnetMask>'
    '<DefaultGateway><ipAddress>192.168.18.1</ipAddress></DefaultGateway>'
    '<PrimaryDNS><ipAddress>8.8.8.8</ipAddress></PrimaryDNS></IPAddress>'
)


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


def _camera_falsa(monkeypatch, xml_get):
    from app.api.endpoints import deployments, maintenance
    enviado = {}

    def req(metodo, url, user, password, body=None, timeout=0):
        if metodo == "GET":
            return _Resp(200, xml_get)
        enviado["body"] = body
        return _Resp(200, '<ResponseStatus><statusCode>1</statusCode><statusString>OK</statusString></ResponseStatus>')
    monkeypatch.setattr(deployments, "_hik_request", req)
    monkeypatch.setattr(maintenance, "_reach", lambda ip: ip)
    return maintenance, enviado


def test_troca_de_ip_firmware_novo_muda_o_ip_de_verdade(monkeypatch):
    m, enviado = _camera_falsa(monkeypatch, REDE_NOVA)
    ok, _msg = m._hik_trocar_ip("192.168.18.51", "192.168.18.60", "255.255.254.0", "192.168.18.1",
                                "", "", "admin", "x")
    assert ok
    corpo = enviado["body"]
    assert "192.168.18.60" in corpo and "static" in corpo  # antes: PUT igual ao GET
    assert "isapi.org" in corpo  # volta no namespace que a camera usa
    assert "8.8.8.8" in corpo  # o resto da configuracao e preservado


def test_troca_de_ip_formato_desconhecido_nao_manda_nada(monkeypatch):
    m, enviado = _camera_falsa(monkeypatch, '<IPAddress xmlns="urn:outro"><x/></IPAddress>')
    ok, msg = m._hik_trocar_ip("1.1.1.1", "1.1.1.2", "255.255.255.0", "1.1.1.254", "", "", "a", "b")
    assert not ok and "nada foi alterado" in msg
    assert "body" not in enviado


# --- IP real: nenhum fluxo vai ao equipamento fora das redes do conector -------

def _fora_do_mapa(monkeypatch):
    from app.services import recorder_xray as X
    monkeypatch.setattr(X._vnat, "has_mapping", lambda cid: True)
    monkeypatch.setattr(X._vnat, "virtual_ip_for", lambda cid, ip: ip)


def test_driver_da_investigacao_recusa_ip_real(monkeypatch):
    from app.services.recorder_driver import ErroDriver, Gravador
    _fora_do_mapa(monkeypatch)
    with pytest.raises(ErroDriver, match="nao esta nas redes"):
        Gravador("192.168.18.80", "admin", "x", 80, "c1", marca="hikvision")


def test_escrita_no_gravador_recusa_ip_real(monkeypatch):
    from app.services import recorder_write as W
    _fora_do_mapa(monkeypatch)
    with pytest.raises(W.ErroGravador, match="nao esta nas redes"):
        W._base("192.168.18.80", 80, "c1")


def test_conector_sem_mapa_nao_e_afetado(monkeypatch):
    from app.services import recorder_xray as X
    monkeypatch.setattr(X._vnat, "has_mapping", lambda cid: False)
    X.conferir_alcance("10.0.0.5", "c-sem-mapa")  # nao levanta
    X.conferir_alcance("10.0.0.5", "")
