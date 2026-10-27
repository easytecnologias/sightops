"""Switch Provedores + links dos provedores do rack: API do RouterOS so de
leitura, alcance so pelo IP virtual, senha presa ao destino, leitura e caminho
ate o Zabbix. Equipamento ficticio (sem rede)."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.endpoints import tools
from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import mapa_rack, rack_links, routeros_api, switch_provedores as SP
from app.services.kmz_ops import kmz_to_geojson


def test_api_routeros_so_aceita_leitura():
    ok = routeros_api._comando_de_leitura
    assert ok(["/interface/print"]) and ok(["/system/identity/print"])
    assert ok(["/interface/ethernet/monitor", "=numbers=sfp-sfpplus4", "=once="])
    assert not ok(["/interface/ethernet/monitor", "=numbers=sfp-sfpplus4"])  # sem once fica rodando
    for cmd in (["/interface/set", "=disabled=yes"], ["/system/reboot"], ["/user/add"], ["/ip/route/add"],
                ["/interface/print=x"], ["interface/print"]):
        assert not ok(cmd), cmd


def test_toda_chave_de_metrica_esta_na_busca_do_zabbix():
    """Chave fora de wanted_keys: o item.get nao acha, o sync tenta recriar, o
    Zabbix recusa a duplicata e o sync do CLIENTE INTEIRO para."""
    fonte = Path("app/services/zabbix_monitoring_service.py").read_text(encoding="utf-8")
    bloco_metricas = fonte[fonte.index("metricas_por_tipo = {"):fonte.index("so_se_presente =")]
    bloco_busca = fonte[fonte.index("wanted_keys = ["):fonte.index("items = _call(", fonte.index("wanted_keys = ["))]
    metricas = set(re.findall(r'"(sightops\.[a-z0-9_]+)"', bloco_metricas))
    busca = set(re.findall(r'"(sightops\.[a-z0-9_]+)"', bloco_busca))
    assert {"sightops.link_in_bps", "sightops.sfp_rx_dbm"} <= metricas
    assert metricas - busca == set()
    padrao = re.search(r"def sync_monitoring_to_zabbix\(entity_types: tuple\[str, \.\.\.\] = \(([^)]*)\)", fonte).group(1)
    assert {'"switch_provedor"', '"link"', '"pdv"'} <= {x.strip() for x in padrao.split(",")}  # no tuple padrao do sync


class _LeitorFalso:
    """Faz o papel da switch: contadores andam entre leituras."""
    rodada = 0
    falhar = False
    hosts: list = []

    def __init__(self, host, porta, usuario, senha, timeout=8.0):
        _LeitorFalso.hosts.append(host)
        if _LeitorFalso.falhar:
            raise routeros_api.RouterOSErro("sem conexao com x (TimeoutError)")
        self.cred = (usuario, senha)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def ler(self, comando, *args):
        n = _LeitorFalso.rodada
        if comando == "/system/identity/print":
            return [{"name": "SWITCH JARDINS PERUCABA"}]
        if comando == "/system/routerboard/print":
            return [{"model": "CRS317-1G-16S+"}]
        if comando == "/system/resource/print":
            return [{"version": "6.47.7", "uptime": "1w", "cpu-load": "3", "free-memory": "900000000", "total-memory": "1073741824"}]
        if comando == "/system/health/print":
            return [{"voltage": "24.1V", "temperature": "41C"}]
        if comando == "/interface/print":
            return [
                {"name": "sfp-sfpplus4", "type": "ether", "running": "true", "disabled": "false", "comment": "DATACOM-4270-VOETELECOM",
                 "rx-byte": str(1000 + n * 7_500_000), "tx-byte": str(500 + n * 2_500_000), "rx-error": "0", "tx-error": "0"},
                {"name": "sfp-sfpplus9", "type": "ether", "running": "false", "disabled": "false",
                 "rx-byte": "10", "tx-byte": "10", "rx-error": str(n * 4), "tx-error": "0"},
                {"name": "BRIDGE", "type": "bridge", "running": "true"},
            ]
        if comando == "/interface/ethernet/monitor":
            assert "=once=" in args
            return [{"name": "sfp-sfpplus4", "sfp-rx-power": "-8.071dBm", "sfp-tx-power": "-1.578dBm", "rate": "10Gbps",
                     "sfp-vendor-name": "DATACOM", "sfp-vendor-part-number": "DM-SFP10-LR", "sfp-wavelength": "1310nm", "sfp-temperature": "38C"},
                    {"name": "sfp-sfpplus9", "status": "no-link"}]
        raise AssertionError(comando)


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    from app.core import tenant_context
    from app.services import connector_routing_vnat as vnat, db_store

    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path / "camadas")
    monkeypatch.setattr(tools, "_apagar_geradas_do_mapa", lambda *a, **k: None)
    monkeypatch.setattr(tools, "_exige_admin_para_excluir", lambda: None)
    monkeypatch.setattr(SP, "LeitorRouterOS", _LeitorFalso)
    # conector "perucaba" mapeado: 10.80.80.0/28 -> 10.209.201.0/28; resto = IP real (fora do mapa)
    monkeypatch.setattr(vnat, "has_mapping", lambda cid: cid == "perucaba")
    monkeypatch.setattr(vnat, "virtual_ip_for", lambda cid, ip: (
        ip.replace("10.80.80.", "10.209.201.") if cid == "perucaba" and ip.startswith("10.80.80.") else ip))
    SP._ULTIMO.clear()
    _LeitorFalso.rodada, _LeitorFalso.falhar, _LeitorFalso.hosts = 0, False, []
    db_store.init_db()
    tok = set_current_tenant_slug("default")
    sw = SP.salvar({"nome": "SWITCH JARDINS", "site": "PERUCABA", "ip": "10.80.80.7", "connector_id": "perucaba",
                    "usuario": "sightops", "senha": "senha-super-secreta"})["id"]
    d = tmp_path / "camadas"
    d.mkdir()
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           '<Placemark><name>RACK JARDINS</name><Point><coordinates>-36.8,-10.1,0</coordinates></Point></Placemark>'
           '</Document></kml>')
    with zipfile.ZipFile(d / "c1.kmz", "w") as zf:
        zf.writestr("doc.kml", kml)
    (d / "c1.geojson").write_text(json.dumps(kmz_to_geojson(d / "c1.kmz")), encoding="utf-8")
    (d / "c1.meta.json").write_text(json.dumps({"id": "c1", "label": "JARDINS"}), encoding="utf-8")
    r = tools._rack_da_camada("c1", {
        "ponto": "RACK JARDINS", "lat": -10.1, "lng": -36.8,
        "equipamentos": [{"id": "crs", "tipo": "switch", "nome": "SWITCH JARDINS", "switch_id": sw,
                          "portas": [{"id": "sfp-sfpplus4"}, {"id": "sfp-sfpplus9"}]},
                         {"id": "dio", "tipo": "dio", "nome": "DIO PROVEDORES", "portas": [{"id": "P1"}, {"id": "P2"}]}],
        "ligacoes": [{"a": {"eq": "dio", "porta": "P1"}, "b": {"eq": "crs", "porta": "sfp-sfpplus4"}}],
        "provedores": [{"id": "voe", "nome": "VOE TELECOM", "entrada": {"eq": "dio", "porta": "P1"}, "banda_mbps": 1000},
                       {"id": "ara", "nome": "ARA TELECOM", "entrada": {"eq": "crs", "porta": "sfp-sfpplus9"}},
                       {"id": "solto", "nome": "SEM SWITCH", "entrada": {"eq": "dio", "porta": "P2"}}],
    })
    yield {"rack_id": r["rack_id"], "sw": sw, "tmp": tmp_path}
    reset_current_tenant_slug(tok)


def _ents(tipo="link"):
    from app.services import db_store

    with db_store._conn() as c:
        return {r["entity_id"]: dict(r) for r in c.execute(
            "SELECT * FROM monitoring_entities WHERE tenant_slug='default' AND entity_type=?", (tipo,)).fetchall()}


def test_cadastro_recusa_ip_fora_do_conector(cliente):
    base = {"nome": "X", "usuario": "u", "senha": "s"}
    with pytest.raises(ValueError, match="fora das redes"):
        SP.salvar({**base, "ip": "192.168.88.1", "connector_id": "perucaba"})
    with pytest.raises(ValueError, match="rede isolada"):
        SP.salvar({**base, "ip": "10.80.80.9", "connector_id": "sem-mapa"})
    with pytest.raises(ValueError, match="conector"):
        SP.salvar({**base, "ip": "10.80.80.9", "connector_id": ""})
    with pytest.raises(ValueError, match="já está cadastrado"):
        SP.salvar({**base, "ip": "10.80.80.7", "connector_id": "perucaba"})


def test_senha_cifrada_nunca_volta_e_cai_ao_mudar_destino(cliente):
    from app.services import db_store

    lista = SP.listar()
    assert lista[0]["tem_senha"] and "senha_enc" not in lista[0] and "senha-super-secreta" not in json.dumps(lista)
    with db_store._conn() as c:
        assert "senha-super-secreta" not in json.dumps([dict(r) for r in c.execute("SELECT * FROM provider_switches").fetchall()])
    # so o nome: senha fica
    SP.salvar({"id": cliente["sw"], "nome": "SWITCH JARDINS I", "ip": "10.80.80.7", "connector_id": "perucaba", "usuario": "sightops"})
    assert SP.listar()[0]["tem_senha"]
    # outro IP sem senha nova: a senha guardada NAO vai junto
    r = SP.salvar({"id": cliente["sw"], "nome": "SWITCH JARDINS I", "ip": "10.80.80.8", "connector_id": "perucaba", "usuario": "sightops"})
    assert r["precisa_senha"] and not SP.listar()[0]["tem_senha"]
    assert "sem usuário/senha" in SP.testar(cliente["sw"])["erro"] and _LeitorFalso.hosts == []


def test_leitura_so_pelo_ip_virtual_com_portas(cliente):
    r = SP.testar(cliente["sw"])
    assert _LeitorFalso.hosts == ["10.209.201.7"]
    assert r["ok"] and r["modelo"] == "CRS317-1G-16S+" and [p["nome"] for p in r["portas"]] == ["sfp-sfpplus4", "sfp-sfpplus9"]
    assert r["portas"][0]["comentario"] == "DATACOM-4270-VOETELECOM" and r["portas"][0]["sfp_rx_dbm"] == -8.071


def test_coleta_switch_e_links(cliente):
    r = SP.coletar_cliente()
    assert r["switches"] == 1 and r["links"] == 2 and not r["falhas"]     # "SEM SWITCH" nao vira link
    sw = _ents("switch_provedor")[cliente["sw"]]
    assert sw["status"] == "up" and json.loads(sw["detail_json"])["ports_up"] == 1
    links = _ents()
    assert set(links) == {"voe", "ara"}
    voe = json.loads(links["voe"]["detail_json"])
    assert voe["porta"] == "sfp-sfpplus4" and voe["entrada"] == {"eq": "dio", "porta": "P1"}   # pela DIO
    assert voe["link_in_bps"] is None and voe["sfp_rx_dbm"] == -8.071
    assert links["voe"]["site"] == "PERUCABA"
    # segunda leitura 60 s depois: 7,5 MB entraram -> 1 Mbit/s
    for k, (t, rx, tx, err) in list(SP._ULTIMO.items()):
        SP._ULTIMO[k] = (t - 60, rx, tx, err)
    _LeitorFalso.rodada = 1
    SP.coletar_cliente()
    links = _ents()
    voe = json.loads(links["voe"]["detail_json"])
    assert links["voe"]["status"] == "up" and 990_000 <= voe["link_in_bps"] <= 1_010_000 and voe["uso_pct"] == pytest.approx(0.1, abs=0.01)
    assert links["ara"]["status"] in ("unstable", "down") and json.loads(links["ara"]["detail_json"])["link_erros"] == 4
    assert all(k[0] == "default" for k in SP._ULTIMO)   # cache com o cliente na chave


def test_falha_de_leitura_switch_fora_links_sem_leitura(cliente):
    SP.coletar_cliente()
    _LeitorFalso.falhar = True
    r = SP.coletar_cliente()
    assert r["falhas"] and {v["status"] for v in _ents().values()} == {"unknown"}
    # Uma leitura falha nao gera evento (histerese); a segunda seguida derruba.
    assert _ents("switch_provedor")[cliente["sw"]]["status"] == "up"
    SP.coletar_cliente()
    assert _ents("switch_provedor")[cliente["sw"]]["status"] == "down"
    assert SP.listar()[0]["erro"] and SP.listar()[0]["leitura"]["portas"]   # guarda a ultima leitura boa


def test_rack_nao_aceita_switch_de_outro_cliente(cliente):
    tok = set_current_tenant_slug("outro")
    try:
        assert SP.listar() == [] and SP.obter(cliente["sw"]) is None
    finally:
        reset_current_tenant_slug(tok)
    meta = json.loads((cliente["tmp"] / "camadas" / "c1.meta.json").read_text(encoding="utf-8"))
    eqs = meta["racks"][cliente["rack_id"]]["equipamentos"]
    eqs[0]["switch_id"] = "swdeoutro"
    with pytest.raises(HTTPException, match="não encontrada"):
        tools._rack_da_camada("c1", {"id": cliente["rack_id"], "equipamentos": eqs})


def test_switch_em_uso_nao_sai(cliente):
    with pytest.raises(ValueError, match="RACK JARDINS"):
        SP.excluir(cliente["sw"])


def test_provedor_tirado_sai_do_monitoramento(cliente):
    SP.coletar_cliente()
    rack = json.loads((cliente["tmp"] / "camadas" / "c1.meta.json").read_text(encoding="utf-8"))["racks"][cliente["rack_id"]]
    tools._rack_da_camada("c1", {"id": cliente["rack_id"], "provedores": [p for p in rack["provedores"] if p["id"] == "voe"]})
    SP.coletar_cliente()
    assert set(_ents()) == {"voe"}
    assert [l["entity_id"] for l in rack_links.links_do_rack(cliente["rack_id"])] == ["voe"]


def test_switch_id_so_no_tipo_switch():
    eq = {"tipo": "dio", "nome": "D", "portas": [{"id": "P1"}], "switch_id": "sw1"}
    assert "switch_id" not in mapa_rack._equipamentos([eq])[0]
    assert mapa_rack._equipamentos([{**eq, "tipo": "switch"}])[0]["switch_id"] == "sw1"


def test_leitura_com_saude_sfp_e_historico(cliente):
    r = SP.testar(cliente["sw"])
    assert r["temperatura_c"] == 41 and r["tensao_v"] == 24.1 and r["cpu_pct"] == 3
    p4 = r["portas"][0]
    assert p4["sfp_fabricante"] == "DATACOM" and p4["sfp_onda_nm"] == 1310 and p4["sfp_temp_c"] == 38
    # RouterOS 7: um sensor por linha
    assert SP._saude([{"name": "cpu-temperature", "value": "52"}])["temperatura_c"] == 52
    # historico: Testar logo depois troca o ultimo ponto; 1 min depois acrescenta
    hist = SP.listar()[0]["leitura"]["hist"]["sfp-sfpplus4"]
    assert len(hist) == 1 and hist[0][3] == -8.071
    SP.testar(cliente["sw"])
    assert len(SP.listar()[0]["leitura"]["hist"]["sfp-sfpplus4"]) == 1
    leitura = SP.listar()[0]["leitura"]
    leitura["hist"]["sfp-sfpplus4"][0][0] -= 60
    pts = SP._com_historico(json.dumps(leitura), SP.ler(SP.obter(cliente["sw"])))["hist"]["sfp-sfpplus4"]
    assert len(pts) == 2
    many = {"hist": {"sfp-sfpplus4": [[i, 1, 1, -8.0] for i in range(100)]}}
    assert len(SP._com_historico(json.dumps(many), SP.ler(SP.obter(cliente["sw"])))["hist"]["sfp-sfpplus4"]) == SP.HIST_PONTOS
