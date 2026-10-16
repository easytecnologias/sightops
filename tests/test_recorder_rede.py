"""Rede do gravador: conferencias que travam o que quebra, aplicacao que procura
o gravador no endereco novo e atualiza inventario + senha salva."""
from __future__ import annotations

import ipaddress
import time
from urllib.parse import parse_qsl, unquote

import pytest

from app.services import recorder_driver as rd
from app.services import recorder_rede as rr

ATUAL = {"ip": "10.10.10.120", "mascara": "255.255.254.0", "gateway": "10.10.10.1", "dns1": "", "dns2": "",
         "http": "8081", "tcp": "37777", "https": "443", "rtsp": "554", "mac": "d8:36:5f:cf:3d:66"}
REDES = [ipaddress.IPv4Network("10.10.10.0/23")]


def novo(**k):
    d = {x: ATUAL[x] for x in rr.CAMPOS}
    d.update(k)
    return d


def grave(checks):
    return [c["titulo"] for c in checks if c["grave"]]


def test_ip_fora_do_conector_trava():
    c = rr.conferir(ATUAL, novo(ip="192.168.1.50", gateway="192.168.1.1", mascara="255.255.255.0"), "c1", arp=[], redes=REDES)
    assert "Alcançável pelo conector" in grave(c)


def test_ip_em_uso_trava_mas_o_proprio_mac_nao():
    arp = [("10.10.10.121", "aa:bb:cc:00:00:01"), ("10.10.10.122", "D8-36-5F-CF-3D-66")]
    assert "IP livre" in grave(rr.conferir(ATUAL, novo(ip="10.10.10.121"), "c1", arp=arp, redes=REDES))
    assert "IP livre" not in grave(rr.conferir(ATUAL, novo(ip="10.10.10.122"), "c1", arp=arp, redes=REDES))


def test_gateway_fora_da_mascara_e_portas_repetidas_travam():
    c = rr.conferir(ATUAL, novo(gateway="10.10.20.1", rtsp="8081"), "c1", arp=[], redes=REDES)
    assert {"Gateway na mesma rede", "Portas sem conflito"} <= set(grave(c))


def test_sem_arp_nao_trava_mas_avisa():
    c = rr.conferir(ATUAL, novo(ip="10.10.10.130"), "c1", arp=None, redes=REDES)
    livre = next(x for x in c if x["titulo"] == "IP livre")
    assert not livre["ok"] and not livre["grave"] and not grave(c)


def test_nada_mudou_trava():
    assert "Há algo para mudar" in grave(rr.conferir(ATUAL, novo(), "", arp=[], redes=REDES))


def test_mudancas_so_o_que_mudou():
    m = rr.mudancas(ATUAL, novo(ip="10.10.10.121", dns1="1.1.1.1"))
    assert [(x["chave"], x["para"]) for x in m] == [("Network.eth0.IPAddress", "10.10.10.121"),
                                                      ("Network.eth0.DnsServers[0]", "1.1.1.1")]


class GravadorDeRede:
    """CGI Intelbras da tabela Network: setConfig troca o IP e a resposta cai."""

    def __init__(self):
        self.estado = {rr.CAMPOS[k]: v for k, v in ATUAL.items() if k in rr.CAMPOS}
        self.estado["Network.eth0.PhysicalAddress"] = ATUAL["mac"]
        self.pedidos = []
        self.sets = []

    def __call__(self, url):
        caminho = url.split("://", 1)[1].split("/", 1)[1]
        self.pedidos.append(caminho)
        if "action=getConfig" in caminho:
            nome = caminho.split("name=", 1)[1]
            return 200, "\n".join(f"table.{k}={v}" for k, v in self.estado.items() if k.split(".", 1)[0] == nome)
        if "setConfig" in caminho:
            qs = [(unquote(k), v) for k, v in parse_qsl(caminho.split("?", 1)[1]) if k != "action"]
            self.sets.append([k for k, _ in qs])
            primeira = qs[0][0].split(".", 1)[0]
            for k, v in qs:
                if k.split(".", 1)[0] == primeira:   # como a Intelbras: so a 1a tabela
                    self.estado[k] = v
            if any(k in ("Network.eth0.IPAddress", "Web.Port") for k, _ in qs):
                return None, "conexao cortada"   # muda de endereco no meio da resposta
            return 200, "OK"
        if "getCurrentTime" in caminho:
            return 200, f"result={time.strftime('%Y-%m-%d %H:%M:%S')}"
        return 404, ""


def _g(falso, host="10.10.10.120", porta=8081):
    return rd.Gravador(host, "admin", "x", porta, pedir=falso, marca="intelbras")


def _esperar(job_id, tenant="t1", seg=5):
    fim = time.time() + seg
    while time.time() < fim:
        j = rr.situacao(job_id, tenant)
        if j["estado"] != "rodando":
            return j
        time.sleep(0.05)
    raise AssertionError("job nao terminou")


def test_aplicar_acha_no_endereco_novo_e_atualiza_tudo(tmp_path, monkeypatch):
    falso = GravadorDeRede()
    feito = {}
    monkeypatch.setattr(rr, "atualizar_inventario", lambda *a: feito.setdefault("inv", a) and {"nvr": 31, "dvr": 0})
    monkeypatch.setattr("app.services.recorder_xray._arp_do_conector", lambda c: [])
    monkeypatch.setattr(rr, "_redes_do_conector", lambda c: REDES)
    regs = []
    job = rr.iniciar_aplicacao(_g(falso), novo(ip="10.10.10.121"), "c1", tmp_path, "t1", "elishafan", 8081,
                               lambda h, p: _g(falso, h, p), regs.append, espera_s=2)
    j = _esperar(job["id"])
    assert j["estado"] == "pronto" and j["host"] == "10.10.10.121" and j["http_port"] == 8081
    assert falso.estado["Network.eth0.IPAddress"] == "10.10.10.121"
    assert feito["inv"][:4] == ("10.10.10.120", 8081, "10.10.10.121", 8081)
    assert regs[0]["ok"] and "10.10.10.120 → 10.10.10.121" in regs[0]["titulo"]
    assert list(tmp_path.glob("rede-10.10.10.120-*.json"))      # backup de antes
    assert rr.situacao(job["id"], "outro-cliente") is None      # job de outro tenant nao existe


def test_gravador_que_nao_volta_vira_perdido_e_nao_mexe_no_inventario(tmp_path, monkeypatch):
    falso = GravadorDeRede()
    monkeypatch.setattr(rr, "atualizar_inventario", lambda *a: pytest.fail("nao pode atualizar inventario"))
    monkeypatch.setattr("app.services.recorder_xray._arp_do_conector", lambda c: [])
    monkeypatch.setattr(rr, "_redes_do_conector", lambda c: REDES)
    monkeypatch.setattr(rr, "_procurar", lambda abrir, espera, **k: None)
    regs = []
    job = rr.iniciar_aplicacao(_g(falso), novo(ip="10.10.10.121"), "c1", tmp_path, "t1", "", 8081,
                               lambda h, p: _g(falso, h, p), regs.append, espera_s=1)
    j = _esperar(job["id"])
    assert j["estado"] == "perdido" and "10.10.10.120:8081" in j["erro"] and "ir ao local" in j["erro"]
    assert regs and not regs[0]["ok"]


def test_aplicar_recusa_o_que_a_conferencia_trava(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.recorder_xray._arp_do_conector", lambda c: [])
    monkeypatch.setattr(rr, "_redes_do_conector", lambda c: REDES)
    falso = GravadorDeRede()
    with pytest.raises(rd.ErroDriver):
        rr.iniciar_aplicacao(_g(falso), novo(ip="192.168.1.9"), "c1", tmp_path, "t1", "", 8081,
                             lambda h, p: _g(falso, h, p), lambda r: None)
    assert not any("setConfig" in p for p in falso.pedidos)


def test_atualizar_inventario_troca_host_porta_e_senha(monkeypatch):
    import app.api.endpoints.dvr as dvr
    import app.api.endpoints.nvr as nvr
    import app.services.recorder_credentials as cred
    linhas = {"nvr": [{"host": "10.10.10.120", "http_port": 8081, "channel": 1, "nvr_ip": "10.10.10.120", "remote_connector_id": "c1"},
                      {"host": "10.10.10.99", "http_port": 80, "remote_connector_id": "c1"}], "dvr": []}
    monkeypatch.setattr(nvr, "_read_rows", lambda: linhas["nvr"])
    monkeypatch.setattr(nvr, "_write_rows", lambda r: linhas.__setitem__("nvr", r))
    monkeypatch.setattr(dvr, "_read_rows", lambda: linhas["dvr"])
    monkeypatch.setattr(dvr, "_write_rows", lambda r: linhas.__setitem__("dvr", r))
    salvas, esquecidas = [], []
    monkeypatch.setattr(cred, "save_recorder_credential", lambda *a: salvas.append(a))
    monkeypatch.setattr(cred, "esquecer_recorder_credential", lambda *a: esquecidas.append(a))
    n = rr.atualizar_inventario("10.10.10.120", 8081, "10.10.10.121", 8082, "admin", "s3nha", "c1")
    assert n == {"nvr": 1, "dvr": 0}
    assert linhas["nvr"][0]["host"] == "10.10.10.121" and linhas["nvr"][0]["http_port"] == 8082 and linhas["nvr"][0]["nvr_ip"] == "10.10.10.121"
    assert linhas["nvr"][1]["host"] == "10.10.10.99"
    assert salvas == [("10.10.10.121", 8082, "admin", "s3nha")] and esquecidas == [("10.10.10.120", 8081)]


def test_procurar_desiste_no_limite():
    t = [0.0]
    achou = rr._procurar(lambda: (_ for _ in ()).throw(rd.ErroDriver("x")), 10, intervalo_s=5,
                         dormir=lambda s: t.__setitem__(0, t[0] + s), relogio=lambda: t[0])
    assert achou is None and t[0] >= 10


def test_mesmo_ip_em_outro_site_nao_muda_e_senha_fica(monkeypatch):
    import app.api.endpoints.dvr as dvr
    import app.api.endpoints.nvr as nvr
    import app.services.recorder_credentials as cred
    linhas = {"nvr": [{"host": "192.168.1.10", "http_port": 80, "remote_connector_id": "site-a"},
                      {"host": "192.168.1.10", "http_port": 80, "remote_connector_id": "site-b"}], "dvr": []}
    monkeypatch.setattr(nvr, "_read_rows", lambda: linhas["nvr"])
    monkeypatch.setattr(nvr, "_write_rows", lambda r: linhas.__setitem__("nvr", r))
    monkeypatch.setattr(dvr, "_read_rows", lambda: [])
    monkeypatch.setattr(dvr, "_write_rows", lambda r: None)
    esquecidas = []
    monkeypatch.setattr(cred, "save_recorder_credential", lambda *a: None)
    monkeypatch.setattr(cred, "esquecer_recorder_credential", lambda *a: esquecidas.append(a))
    rr.atualizar_inventario("192.168.1.10", 80, "192.168.1.11", 80, "admin", "x", "site-a")
    assert [r["host"] for r in linhas["nvr"]] == ["192.168.1.11", "192.168.1.10"]
    assert esquecidas == []   # o gravador do site B ainda usa a senha do endereco antigo


def test_campo_vazio_nao_vira_mudanca():
    m = rr.mudancas(ATUAL, novo(gateway="", http="", dns1=""))
    assert m == []


def test_le_portas_das_tabelas_proprias():
    falso = GravadorDeRede()
    r = rr.ler_rede(_g(falso))
    assert (r["http"], r["rtsp"], r["tcp"], r["https"]) == ("8081", "554", "37777", "443")
    assert {p.split("name=")[1] for p in falso.pedidos if "getConfig" in p} == set(rr.TABELAS)
    assert rr.CAMPOS["http"] == "Web.Port" and rr.CAMPOS["tcp"] == "DVRIP.TCPPort"


def test_ip_e_porta_web_juntos_trava():
    c = rr.conferir(ATUAL, novo(ip="10.10.10.121", http="8082"), "c1", arp=[], redes=REDES)
    assert "IP e porta web em vezes separadas" in grave(c)


def test_um_pedido_por_tabela_e_o_que_corta_acesso_por_ultimo(tmp_path, monkeypatch):
    falso = GravadorDeRede()
    monkeypatch.setattr(rr, "atualizar_inventario", lambda *a: {"nvr": 1, "dvr": 0})
    monkeypatch.setattr("app.services.recorder_xray._arp_do_conector", lambda c: [])
    monkeypatch.setattr(rr, "_redes_do_conector", lambda c: REDES)
    job = rr.iniciar_aplicacao(_g(falso), novo(ip="10.10.10.121", rtsp="5554", dns1="1.1.1.1"), "c1", tmp_path, "t1", "",
                               8081, lambda h, p: _g(falso, h, p), lambda r: None, espera_s=2)
    j = _esperar(job["id"])
    assert j["estado"] == "pronto", j
    assert [sorted({k.split(".")[0] for k in s}) for s in falso.sets] == [["RTSP"], ["Network"]]
    assert falso.estado["RTSP.Port"] == "5554" and falso.estado["Network.eth0.IPAddress"] == "10.10.10.121"
    assert falso.estado["Network.eth0.DnsServers[0]"] == "1.1.1.1"
