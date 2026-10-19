"""Gravador Hikvision do JANGADEIROS (DS-7616NXI-K1, 19/10/2026), comportamento
medido no equipamento:

- canal vago responde 403 com ResponseStatus "Invalid Operation" -- o _req
  tratava como senha errada e o "adicionar" abortava antes do POST que cria o
  canal; so sobrescrever o canal 1 "funcionava";
- InputProxy/channels lista so os 7 canais cadastrados de 16;
- relogio em timeMode=manual, 11 h atrasado, fuso CST+3 (-03:00), e a hora
  do Hikvision nao tinha correcao.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from app.services import recorder_avisos as ra
from app.services import recorder_driver as rd
from app.services import recorder_write as W

INVALIDO = ('<?xml version="1.0" encoding="UTF-8"?><ResponseStatus version="1.0" '
            'xmlns="http://www.hikvision.com/ver20/XMLSchema"><statusCode>4</statusCode>'
            '<statusString>Invalid Operation</statusString><subStatusCode>invalidOperation</subStatusCode>'
            '</ResponseStatus>')
OK = '<ResponseStatus><statusCode>1</statusCode><statusString>OK</statusString></ResponseStatus>'


class _Resp:
    def __init__(self, cod, txt):
        self.status_code, self.text = cod, txt


def test_403_invalid_operation_e_resposta_nao_senha_errada(monkeypatch):
    monkeypatch.setattr(W.requests, "request", lambda *a, **k: _Resp(403, INVALIDO))
    assert W._req("PUT", "http://g/ISAPI/ContentMgmt/InputProxy/channels/8", "admin", "x") == (403, INVALIDO)
    # 403 sem corpo ISAPI continua sendo credencial recusada
    monkeypatch.setattr(W.requests, "request", lambda *a, **k: _Resp(403, ""))
    with pytest.raises(W.ErroGravador, match="senha"):
        W._req("GET", "http://g/x", "admin", "x")


class HikComSeteCanais:
    """Canais 1..7 cadastrados; 8+ vagos (403 Invalid Operation, como o real)."""

    def __init__(self):
        self.canais = {n: f"172.16.81.{32 + n}" for n in range(1, 8)}
        self.pedidos: list[str] = []

    def req(self, metodo, url, user, password, corpo=None, tipo="", timeout=0):
        self.pedidos.append(f"{metodo} {url.split('/ISAPI/')[-1]}")
        if url.endswith("/channels/status"):
            ids = "".join(f"<InputProxyChannelStatus><id>{n}</id><online>true</online></InputProxyChannelStatus>"
                          for n in self.canais)
            return 200, f"<InputProxyChannelStatusList>{ids}</InputProxyChannelStatusList>"
        m = re.search(r"/InputProxy/channels/(\d+)$", url)
        if m:
            n = int(m.group(1))
            if metodo == "GET":
                return (200, f"<InputProxyChannel><id>{n}</id><sourceInputPortDescriptor>"
                             f"<ipAddress>{self.canais[n]}</ipAddress></sourceInputPortDescriptor></InputProxyChannel>"
                        ) if n in self.canais else (403, INVALIDO)
            if metodo == "PUT":
                if n not in self.canais:
                    return 403, INVALIDO
                self.canais[n] = re.search(r"<ipAddress>([^<]+)<", corpo.decode()).group(1)
                return 200, OK
        if url.endswith("/InputProxy/channels") and metodo == "POST":
            n = int(re.search(r"<id>(\d+)</id>", corpo.decode()).group(1))
            self.canais[n] = re.search(r"<ipAddress>([^<]+)<", corpo.decode()).group(1)
            return 200, OK
        return 404, ""


@pytest.fixture
def hik(monkeypatch):
    g = HikComSeteCanais()
    monkeypatch.setattr(W, "_req", g.req)
    monkeypatch.setattr(W, "detectar_marca", lambda *a: "hikvision", raising=False)
    monkeypatch.setattr(W, "_base", lambda *a: "http://10.211.66.201")
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    monkeypatch.setattr(W.time, "monotonic", iter(range(0, 10_000, 100)).__next__)
    return g


def _adicionar(canal):
    return W.executar("adicionar", host="172.16.80.201", user="admin", password="x", canal=canal,
                      ip="172.16.81.50", cam_user="admin", cam_senha="s", nome="NOVA", protocolo="HIKVISION")


def test_adicionar_em_canal_vago_cria_pelo_post(hik):
    saida = _adicionar(8)
    assert saida["ok"] and hik.canais[8] == "172.16.81.50"
    assert hik.canais[1] == "172.16.81.33"  # a camera do canal 1 continua la
    assert "POST ContentMgmt/InputProxy/channels" in hik.pedidos


def test_adicionar_nunca_sobrescreve_canal_ocupado(hik):
    with pytest.raises(W.ErroGravador, match="ja tem a camera 172.16.81.33"):
        _adicionar(1)
    assert hik.canais[1] == "172.16.81.33"
    assert not any(p.startswith(("PUT", "POST")) for p in hik.pedidos)


# ------------------------------------------------------------------ relogio
class HikRelogio:
    def __init__(self, atraso_h=11):
        fuso = timezone(timedelta(hours=-3))
        self.hora = datetime.now(timezone.utc).astimezone(fuso) - timedelta(hours=atraso_h, minutes=4)
        self.puts: list[str] = []

    def _xml(self):
        return ('<?xml version="1.0" encoding="UTF-8" ?><Time version="1.0" '
                'xmlns="http://www.hikvision.com/ver20/XMLSchema"><timeMode>manual</timeMode>'
                f'<localTime>{self.hora:%Y-%m-%dT%H:%M:%S}-03:00</localTime><timeZone>CST+3:00:00</timeZone>'
                '<windowsZone>E. South America Standard Time</windowsZone></Time>')

    def pedir(self, url):
        return (200, self._xml()) if url.endswith("/ISAPI/System/time") else (404, "")

    def colocar(self, url, corpo):
        self.puts.append(corpo)
        m = re.search(r"<localTime>([^<]+)</localTime>", corpo)
        self.hora = datetime.fromisoformat(m.group(1))
        return 200, OK


def _g(falso):
    return rd.Gravador("172.16.80.201", "admin", "x", 80, pedir=falso.pedir, colocar=falso.colocar,
                       marca="hikvision")


def test_relogio_do_hikvision_agora_tem_correcao(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "America/Sao_Paulo")
    falso = HikRelogio()
    av = {a["id"]: a for a in ra.avisos_do_gravador(_g(falso))["avisos"]}
    assert av["relogio"]["titulo"].startswith("Relógio 11 h 4 min") and not av["relogio"].get("manual")
    r = ra.corrigir(_g(falso), "relogio", tmp_path, por="elishafan")
    assert r["ok"] and len(falso.puts) == 1
    corpo = falso.puts[0]
    # so a hora muda: fuso, modo e o resto continuam como o gravador tinha
    assert "<timeMode>manual</timeMode>" in corpo and "<timeZone>CST+3:00:00</timeZone>" in corpo
    assert re.search(r"<localTime>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d-03:00</localTime>", corpo)
    reg = ra.ler_registro(tmp_path, r["registro"])
    assert reg["aviso"] == "relogio" and not reg["desfazivel"]


def test_hikvision_continua_sem_correcao_de_configuracao(tmp_path):
    with pytest.raises(rd.ErroDriver):
        ra.corrigir(_g(HikRelogio()), "movimento", tmp_path)
