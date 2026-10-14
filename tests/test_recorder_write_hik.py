"""Escrita de canal no Hikvision: protocolo, porta e conferencia de status.

Caso real (14/10/2026, DS-7616NI da TELHA, InforBR): "Editar camera" com
protocolo Automatico gravou ONVIF:80, o gravador respondeu 200 e a tela disse
"Feito" -- e o canal ficou offline (accessFroDeviceParamFailure). O canal
vizinho, mesma camera, funcionava em HIKVISION:8000.
"""
from __future__ import annotations

import re

from app.services import recorder_write as W

STATUS = (
    '<InputProxyChannelStatusList xmlns="http://www.hikvision.com/ver20/XMLSchema">'
    '<InputProxyChannelStatus version="1.0"><id>9</id><online>{on9}</online>'
    '<chanDetectResult>{det9}</chanDetectResult></InputProxyChannelStatus>'
    '<InputProxyChannelStatus version="1.0"><id>10</id><online>true</online>'
    '<chanDetectResult>connect</chanDetectResult></InputProxyChannelStatus>'
    '</InputProxyChannelStatusList>'
)


class GravadorFalso:
    """Aceita qualquer PUT; o canal so fica online com o protocolo `bom`."""

    def __init__(self, bom: str | None):
        self.bom = bom
        self.gravado = ""
        self.puts: list[str] = []

    def req(self, metodo, url, user, password, corpo=None, tipo="", timeout=0):
        if metodo == "PUT":
            self.gravado = corpo.decode()
            proto = re.search(r"<proxyProtocol>(\w+)</proxyProtocol>", self.gravado).group(1)
            porta = re.search(r"<managePortNo>(\d+)</managePortNo>", self.gravado).group(1)
            self.puts.append(f"{proto}:{porta}")
            return 200, "<ResponseStatus><statusCode>1</statusCode></ResponseStatus>"
        if url.endswith("/channels/status"):
            on = bool(self.puts) and self.puts[-1].startswith(self.bom or "-")
            return 200, STATUS.format(on9="true" if on else "false",
                                      det9="connect" if on else "accessFroDeviceParamFailure")
        return 404, ""


def _editar(monkeypatch, bom, protocolo=""):
    g = GravadorFalso(bom)
    monkeypatch.setattr(W, "_req", g.req)
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    monkeypatch.setattr(W.time, "monotonic", iter(range(0, 10_000, 100)).__next__)
    saida = W._hik_editar("http://gravador", "admin", "x", canal=9, ip="10.50.11.41",
                          cam_user="admin", cam_senha="s", nome="IPCamera 09",
                          protocolo=protocolo, porta=None)
    return g, saida


def test_automatico_comeca_por_hikvision_na_8000(monkeypatch):
    g, saida = _editar(monkeypatch, bom="HIKVISION")
    assert g.puts == ["HIKVISION:8000"]
    assert saida["online"] is True


def test_automatico_cai_para_onvif_quando_hikvision_nao_conecta(monkeypatch):
    g, saida = _editar(monkeypatch, bom="ONVIF")
    assert g.puts == ["HIKVISION:8000", "ONVIF:80"]
    assert saida["online"] is True and "ONVIF:80" in saida["comando"]


def test_nenhum_conecta_avisa_em_vez_de_dizer_feito(monkeypatch):
    g, saida = _editar(monkeypatch, bom=None)
    assert saida["online"] is False
    assert "accessFroDeviceParamFailure" in saida["aviso"]
    # Fica o primeiro protocolo, nao o ultimo tentado.
    assert g.puts[-1] == "HIKVISION:8000"


def test_hikvision_escolhido_usa_a_8000_nao_a_80(monkeypatch):
    g, _ = _editar(monkeypatch, bom="HIKVISION", protocolo="HIKVISION")
    assert g.puts == ["HIKVISION:8000"]


def test_onvif_escrito_pela_tela_e_normalizado(monkeypatch):
    g, _ = _editar(monkeypatch, bom="ONVIF", protocolo="Onvif")
    assert g.puts == ["ONVIF:80"]


def test_private_da_intelbras_vira_automatico_no_hikvision(monkeypatch):
    g, _ = _editar(monkeypatch, bom="HIKVISION", protocolo="Private")
    assert g.puts == ["HIKVISION:8000"]
