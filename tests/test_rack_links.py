"""Links dos provedores do rack: API do RouterOS so de leitura, coleta, senha
fora do meta e caminho ate o Zabbix. Equipamento ficticio (sem rede)."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

from app.api.endpoints import tools
from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import mapa_rack, rack_links, routeros_api
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


def test_coleta_validada_no_rack():
    eq = {"tipo": "switch", "nome": "CRS", "portas": [{"id": "sfp1"}], "coleta": {"ativo": True, "ip": "10.80.80.7", "conector": "abc"}}
    out = mapa_rack._equipamentos([eq])[0]
    assert out["coleta"] == {"ativo": True, "ip": "10.80.80.7", "porta": 8728, "conector": "abc"}
    with pytest.raises(mapa_rack.RackErro):
        mapa_rack._equipamentos([{**eq, "coleta": {"ativo": True, "ip": "10.80.80"}}])
    with pytest.raises(mapa_rack.RackErro):
        mapa_rack._equipamentos([{**eq, "coleta": {"ativo": True, "ip": ""}}])
    with pytest.raises(mapa_rack.RackErro, match="conector"):
        mapa_rack._equipamentos([{**eq, "coleta": {"ativo": True, "ip": "10.80.80.7"}}])
    # "nao" e string verdadeira em Python: tem que desligar mesmo assim
    assert mapa_rack._equipamentos([{**eq, "coleta": {"ativo": "nao", "ip": "10.80.80.7"}}])[0]["coleta"]["ativo"] is False
    # DIO nao tem leitura
    assert "coleta" not in mapa_rack._equipamentos([{**eq, "tipo": "dio"}])[0]


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
        if comando == "/interface/print":
            return [
                {"name": "sfp-sfpplus4", "type": "ether", "running": "true", "disabled": "false",
                 "rx-byte": str(1000 + n * 7_500_000), "tx-byte": str(500 + n * 2_500_000), "rx-error": "0", "tx-error": "0"},
                {"name": "sfp-sfpplus9", "type": "ether", "running": "false", "disabled": "false",
                 "rx-byte": "10", "tx-byte": "10", "rx-error": str(n * 4), "tx-error": "0"},
            ]
        if comando == "/interface/ethernet/monitor":
            assert "=once=" in args
            return [{"name": "sfp-sfpplus4", "sfp-rx-power": "-8.071dBm", "sfp-tx-power": "-1.578dBm", "rate": "10Gbps"},
                    {"name": "sfp-sfpplus9", "status": "no-link"}]
        raise AssertionError(comando)


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    from app.core import tenant_context
    from app.services import db_store

    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path / "camadas")
    monkeypatch.setattr(tools, "_apagar_geradas_do_mapa", lambda *a, **k: None)
    monkeypatch.setattr(tools, "_exige_admin_para_excluir", lambda: None)
    monkeypatch.setattr(rack_links, "LeitorRouterOS", _LeitorFalso)
    from app.services import connector_routing_vnat as vnat
    # conector "perucaba" mapeado: 10.80.80.0/28 -> 10.209.201.0/28; resto = IP real (fora do mapa)
    monkeypatch.setattr(vnat, "has_mapping", lambda cid: cid == "perucaba")
    monkeypatch.setattr(vnat, "virtual_ip_for", lambda cid, ip: (
        ip.replace("10.80.80.", "10.209.201.") if cid == "perucaba" and ip.startswith("10.80.80.") else ip))
    _LeitorFalso.hosts = []
    rack_links._ULTIMO.clear()
    _LeitorFalso.rodada, _LeitorFalso.falhar = 0, False
    db_store.init_db()
    tok = set_current_tenant_slug("default")
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
        "equipamentos": [{"id": "crs", "tipo": "switch", "nome": "SWITCH JARDINS",
                          "portas": [{"id": "sfp-sfpplus4"}, {"id": "sfp-sfpplus9"}],
                          "coleta": {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"}}],
        "provedores": [{"id": "voe", "nome": "VOE TELECOM", "entrada": {"eq": "crs", "porta": "sfp-sfpplus4"}, "banda_mbps": 1000},
                       {"id": "ara", "nome": "ARA TELECOM", "entrada": {"eq": "crs", "porta": "sfp-sfpplus9"}}],
    })
    yield {"rack_id": r["rack_id"], "tmp": tmp_path}
    reset_current_tenant_slug(tok)


def _links():
    from app.services import db_store

    with db_store._conn() as c:
        return {r["entity_id"]: dict(r) for r in c.execute(
            "SELECT * FROM monitoring_entities WHERE tenant_slug='default' AND entity_type='link'").fetchall()}


def test_senha_criptografada_e_fora_do_mapa(cliente):
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "senha-super-secreta", {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"})
    meta = (cliente["tmp"] / "camadas" / "c1.meta.json").read_text(encoding="utf-8")
    assert "senha-super-secreta" not in meta
    from app.services import db_store
    with db_store._conn() as c:
        bruto = " ".join(str(dict(r)["v"]) for r in c.execute("SELECT v FROM json_state").fetchall())
    assert "senha-super-secreta" not in bruto
    assert rack_links._credencial("c1", cliente["rack_id"], "crs", {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"}) == ("sightops", "senha-super-secreta")


def test_sem_senha_fica_sem_leitura_nao_caido(cliente):
    rack_links.coletar_cliente()
    links = _links()
    assert {k: v["status"] for k, v in links.items()} == {"voe": "unknown", "ara": "unknown"}
    assert "sem usuário/senha" in json.loads(links["voe"]["detail_json"])["erro"]


def test_coleta_status_trafego_e_sinal(cliente):
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "x", {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"})
    r = rack_links.coletar_cliente()
    assert r["switches"] == 1 and r["links"] == 2 and not r["falhas"]
    d = json.loads(_links()["voe"]["detail_json"])
    assert d["sfp_rx_dbm"] == -8.071 and d["link_in_bps"] is None   # 1a leitura: sem bit/s ainda
    rack_links._ULTIMO[next(iter(rack_links._ULTIMO))]  # cache existe
    # segunda leitura 60 s depois: 7,5 MB entraram -> 1 Mbit/s
    for k, (t, rx, tx, err) in list(rack_links._ULTIMO.items()):
        rack_links._ULTIMO[k] = (t - 60, rx, tx, err)
    _LeitorFalso.rodada = 1
    rack_links.coletar_cliente()
    links = _links()
    d = json.loads(links["voe"]["detail_json"])
    assert links["voe"]["status"] == "up"
    assert 990_000 <= d["link_in_bps"] <= 1_010_000 and d["uso_pct"] == pytest.approx(0.1, abs=0.01)
    ara = json.loads(links["ara"]["detail_json"])
    assert links["ara"]["status"] in ("unstable", "down") and ara["link_erros"] == 4


def test_falha_de_leitura_nao_derruba_o_link(cliente):
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "x", {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"})
    rack_links.coletar_cliente()
    _LeitorFalso.falhar = True
    r = rack_links.coletar_cliente()
    assert r["falhas"] and {v["status"] for v in _links().values()} == {"unknown"}


def test_provedor_tirado_sai_do_monitoramento(cliente):
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "x", {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"})
    rack_links.coletar_cliente()
    rack = json.loads((cliente["tmp"] / "camadas" / "c1.meta.json").read_text(encoding="utf-8"))["racks"][cliente["rack_id"]]
    tools._rack_da_camada("c1", {"id": cliente["rack_id"], "provedores": [p for p in rack["provedores"] if p["id"] == "voe"]})
    rack_links.coletar_cliente()
    assert set(_links()) == {"voe"}
    assert [l["entity_id"] for l in rack_links.links_do_rack(cliente["rack_id"])] == ["voe"]


def test_cache_de_contadores_separado_por_cliente(cliente):
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "x", {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"})
    rack_links.coletar_cliente()
    assert all(k[0] == "default" for k in rack_links._ULTIMO)


def test_coleta_so_pelo_ip_virtual(cliente):
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "x", {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"})
    rack_links.coletar_cliente()
    assert _LeitorFalso.hosts == ["10.209.201.7"]   # nunca o IP real


def _trocar_coleta(cliente, **coleta):
    meta = json.loads((cliente["tmp"] / "camadas" / "c1.meta.json").read_text(encoding="utf-8"))
    eqs = meta["racks"][cliente["rack_id"]]["equipamentos"]
    eqs[0]["coleta"] = {**eqs[0]["coleta"], **coleta}
    tools._rack_da_camada("c1", {"id": cliente["rack_id"], "equipamentos": eqs})


def test_ip_fora_do_conector_nao_abre_conexao(cliente):
    """IP fora das redes mapeadas do conector daria o IP real -- pode ser de
    outro cliente. Nao conecta e nao manda a senha."""
    _trocar_coleta(cliente, ip="192.168.88.1")
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "x",
                                 {"ativo": True, "ip": "192.168.88.1", "conector": "perucaba"})
    r = rack_links.coletar_cliente()
    assert _LeitorFalso.hosts == [] and "fora das redes do conector" in r["falhas"][0]
    _trocar_coleta(cliente, ip="10.80.80.7", conector="sem-mapa")
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "x",
                                 {"ativo": True, "ip": "10.80.80.7", "conector": "sem-mapa"})
    r = rack_links.coletar_cliente()
    assert _LeitorFalso.hosts == [] and "não tem rede isolada" in r["falhas"][0]


def test_trocar_o_ip_invalida_a_senha(cliente):
    """Operador edita o rack e aponta para outro IP: a senha guardada pelo
    admin para o IP antigo nao vai junto."""
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "x", {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"})
    assert rack_links.tem_credencial("c1", cliente["rack_id"], "crs", {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"})
    _trocar_coleta(cliente, ip="10.80.80.9")
    r = rack_links.coletar_cliente()
    assert _LeitorFalso.hosts == [] and "guardar a senha de novo" in r["falhas"][0]
    assert not rack_links.tem_credencial("c1", cliente["rack_id"], "crs",
                                         {"ativo": True, "ip": "10.80.80.9", "conector": "perucaba"})


def test_provedor_pela_dio_e_medido_na_porta_da_switch(cliente):
    """Caso real do Jardins: a VOE entra na DIO P1, e a DIO P1 esta ligada na
    sfp4 da switch. O link e medido na sfp4; sem ligacao ate a switch, nao ha
    o que medir (e nao vira link "sem leitura" alarmando a toa)."""
    meta = json.loads((cliente["tmp"] / "camadas" / "c1.meta.json").read_text(encoding="utf-8"))
    rack = meta["racks"][cliente["rack_id"]]
    eqs = rack["equipamentos"] + [{"id": "dio", "tipo": "dio", "nome": "DIO PROVEDORES", "portas": [{"id": "P1"}, {"id": "P2"}]}]
    provs = [{"id": "voe", "nome": "VOE TELECOM", "entrada": {"eq": "dio", "porta": "P1"}},
             {"id": "solto", "nome": "SEM SWITCH", "entrada": {"eq": "dio", "porta": "P2"}}]
    tools._rack_da_camada("c1", {"id": cliente["rack_id"], "equipamentos": eqs, "provedores": provs,
                                 "ligacoes": [{"a": {"eq": "dio", "porta": "P1"}, "b": {"eq": "crs", "porta": "sfp-sfpplus4"}}]})
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "x",
                                 {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"})
    rack_links.coletar_cliente()
    links = _links()
    assert set(links) == {"voe"}
    d = json.loads(links["voe"]["detail_json"])
    assert d["porta"] == "sfp-sfpplus4" and d["entrada"] == {"eq": "dio", "porta": "P1"} and d["sfp_rx_dbm"] == -8.071


def test_local_do_link_e_o_do_conector(cliente):
    from app.services import db_store

    with db_store._conn() as c:
        c.execute("INSERT INTO monitoring_entities(tenant_slug,entity_key,entity_type,entity_id,site,display_name,status) "
                  "VALUES('default','connector:perucaba','connector','perucaba','PERUCABA','PERUCABA','up')")
    rack_links.salvar_credencial("c1", cliente["rack_id"], "crs", "sightops", "x",
                                 {"ativo": True, "ip": "10.80.80.7", "conector": "perucaba"})
    rack_links.coletar_cliente()
    assert {v["site"] for v in _links().values()} == {"PERUCABA"}
