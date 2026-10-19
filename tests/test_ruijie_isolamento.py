"""Ruijie isolado igual ao MikroTik: rede Docker propria (rjc<N>), tabela 100N,
faixa virtual -- e nenhuma rota de cliente na tabela geral do servidor."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _modulo(nome, caminho):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


prov = _modulo("iso_provisioner_t", RAIZ / "deploy" / "iso-provisioner" / "iso_provisioner.py")
sys.path.insert(0, str(RAIZ / "scripts"))
import sightops_ruijie_vpn_sync as sync  # noqa: E402

from app.services import connector_service as cs  # noqa: E402
from app.services import connector_routing_vnat as vnat  # noqa: E402


# ---------------------------------------------------------------- sync (tunel)

def test_tunel_nunca_sobe_na_rede_do_host():
    args = sync.run_args("abc", 14)
    assert "host" not in args[args.index("--network") + 1]
    assert args[args.index("--network") + 1] == "sightops-rj14"
    assert args[args.index("--ip") + 1] == "10.203.14.2"
    assert "net.ipv4.ip_forward=1" in args
    script = args[-1]
    # so SightOps -> cliente e a resposta; nada nasce do lado do cliente
    assert "iptables -P FORWARD DROP" in script
    assert "-i eth0 -o tun+ -j ACCEPT" in script
    assert "-i tun+ -o eth0 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT" in script
    assert script.index("iptables -P FORWARD DROP") < script.index("exec openvpn")


def test_rede_propria_por_indice():
    assert sync.rede_isolada(14) == {"nome": "sightops-rj14", "bridge": "rjc14", "subnet": "10.203.14.0/29",
                                     "gateway": "10.203.14.1", "ip": "10.203.14.2"}
    with pytest.raises(ValueError):
        sync.rede_isolada(0)


def test_ganhar_indice_recria_o_tunel_antigo_da_rede_geral():
    item = {"id": "abc", "vpn_config": "cfg", "vpn_username": "sightops", "vpn_password": "x", "iso_index": 14}
    antigo = sync.config_hash("cfg", "sightops", "x")  # tunel de antes, na rede do host
    plano = sync.plan_actions([item], running_ids=["abc"], cached_hashes={"abc": antigo})
    assert plano["recreate"] == ["abc"]
    novo = sync.config_hash("cfg", "sightops", "x", 14)
    assert sync.plan_actions([item], running_ids=["abc"], cached_hashes={"abc": novo})["noop"] == ["abc"]


def test_sem_indice_nao_sobe_tunel(monkeypatch, capsys):
    monkeypatch.setattr(sync, "fetch_desired_state", lambda: [
        {"id": "abc", "name": "GW", "vpn_config": "c", "vpn_username": "u", "vpn_password": "p", "iso_index": None}])
    monkeypatch.setattr(sync, "running_container_ids", lambda: [])
    monkeypatch.setattr(sync, "load_cached_hashes", lambda: {})
    iniciados = []
    monkeypatch.setattr(sync, "start_container", lambda *a: iniciados.append(a))
    monkeypatch.setattr(sync, "remove_orphan_networks", lambda idx: None)
    sync.main()
    assert iniciados == [] and "aguardando indice" in capsys.readouterr().out


# ------------------------------------------------------- provisionador (host)

def test_lans_do_gateway_ou_so_o_gateway_antes_da_primeira_coleta():
    assert prov._lans_ruijie({"gateway_host": "172.16.80.1"}) == ["172.16.80.1/32"]
    assert prov._lans_ruijie({"gateway_host": "172.16.80.1",
                              "host": {"lan_networks": ["172.16.80.0/23", "172.16.180.0/24"]}}) == [
        "172.16.80.0/23", "172.16.180.0/24"]


def _sh_falso(monkeypatch, existe=True, rotas=""):
    feitos = []

    def sh(argv, stdin=None, check=False):
        feitos.append(argv)
        if argv[:3] == ["ip", "link", "show"]:
            return (0 if existe else 1), ""
        if argv[:4] == ["ip", "-4", "route", "show"]:
            return 0, rotas
        if argv[:3] == ["iptables", "-t", "filter"] or argv[:2] == ["iptables", "-t"]:
            return (1 if "-C" in argv else 0), ""
        return 0, ""
    monkeypatch.setattr(prov, "sh", sh)
    return feitos


def test_provisionador_poe_rotas_so_na_tabela_do_conector(monkeypatch):
    feitos = _sh_falso(monkeypatch, rotas="172.16.99.0/24 via 10.203.14.2 dev rjc14\n")
    lans = ["172.16.80.0/23", "172.16.180.0/24"]
    vm = prov.virtual_map(14, lans)
    msg = prov._apply_ruijie(14, "gw", lans, vm)
    assert "rjc14 ok" in msg
    rotas = [a for a in feitos if a[:3] == ["ip", "route", "replace"]]
    assert rotas and all(a[-2:] == ["table", "1014"] and "via" in a and "10.203.14.2" in a for a in rotas)
    # nenhuma rota de cliente na tabela geral
    assert not any(a[:3] == ["ip", "route", "replace"] and "table" not in a for a in feitos)
    # rota velha da tabela do conector sai
    assert ["ip", "route", "del", "172.16.99.0/24", "table", "1014"] in feitos
    # faixa virtual dentro do slice do indice 14, NETMAP + marca -> tabela
    assert all(prov.ipaddress.ip_network(v).subnet_of(prov.virtual_slice(14)) for _r, v in vm)
    assert any("NETMAP" in a for a in feitos) and any("0x510e" in a for a in feitos)
    assert ["ip", "rule", "add", "fwmark", "0x510e", "table", "1014", "pref", "20014"] in feitos
    # do container para fora, so resposta
    assert any(a[-6:] == ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"] and "rjc14" in a
               for a in feitos)


def test_provisionador_espera_o_tunel_existir(monkeypatch):
    feitos = _sh_falso(monkeypatch, existe=False)
    assert "aguardando tunel" in prov._apply_ruijie(14, "gw", ["172.16.80.0/23"], [])
    assert not any(a[:2] == ["ip", "route"] for a in feitos)


def test_reconcile_trata_ruijie_e_grava_mapa(monkeypatch, tmp_path):
    conns = [{"id": "gw", "type": "ruijie", "iso_index": 14, "gateway_host": "172.16.80.1",
              "host": {"lan_networks": ["172.16.80.0/23"]}}]
    monkeypatch.setattr(prov, "VNAT_MAP", str(tmp_path / "map.json"))
    monkeypatch.setattr(prov, "wg_privkey", lambda: "k")
    monkeypatch.setattr(prov, "load_connectors", lambda: conns)
    monkeypatch.setattr(prov, "existing_wgc_indices", lambda: [])
    monkeypatch.setattr(prov, "existing_rjc_indices", lambda: [14, 15])
    _sh_falso(monkeypatch)
    derrubados = []
    monkeypatch.setattr(prov, "teardown_ruijie", lambda n: derrubados.append(n) or "x")
    logs = prov.reconcile_once()
    assert any("rjc14 ok" in l for l in logs)
    assert derrubados == [15]  # rjc15 sem conector: regras saem
    mapa = json.loads((tmp_path / "map.json").read_text())
    assert mapa["gw"][0]["real_cidr"] == "172.16.80.0/23"


# ----------------------------------------------------------------------- app

@pytest.fixture
def conectores(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CONNECTORS_PATH", tmp_path / "connectors.json")
    monkeypatch.setattr(cs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cs, "decrypt", lambda v: "senha")
    cs._ruijie_sessions.clear()
    return cs


def test_conector_existente_ganha_indice_e_coleta_pelo_ip_virtual(conectores, monkeypatch):
    cs._save_connectors([
        {"id": "mk", "type": "routeros", "tenant_slug": "t9", "iso_index": 1},
        {"id": "gw", "type": "ruijie", "tenant_slug": "t1", "gateway_host": "172.16.80.1",
         "gateway_user": "admin", "password_enc": "x", "inventory": {}},
    ])
    monkeypatch.setattr(vnat, "_load_map", lambda: {
        "gw": [(vnat.ipaddress.ip_network("172.16.80.0/23"), vnat.ipaddress.ip_network("10.210.128.0/23"))]})
    chamados = []

    def coleta(host, *a, **k):
        chamados.append(host)
        raise TimeoutError("sem rede no teste")
    monkeypatch.setattr(cs, "ruijie_collect_status", coleta)
    cs.ruijie_poll_all()
    gw = next(r for r in cs._load_connectors() if r["id"] == "gw")
    assert gw["iso_index"] == 8  # Ruijie comeca depois dos manuais (wgc1..7)
    assert chamados == ["10.210.128.1"]  # IP virtual, nunca o real
    assert gw["ruijie_poll"]["host"] == "172.16.80.1"  # a prova de posse e sobre o IP real


def test_cadastro_novo_ja_nasce_com_indice(conectores, monkeypatch):
    monkeypatch.setattr(cs, "encrypt", lambda v: v)
    monkeypatch.setattr(cs, "get_current_tenant_slug", lambda: "t1")
    r = cs.create_connector({"type": "ruijie", "gateway_host": "172.16.80.1", "gateway_password": "x"})
    assert cs._load_connectors()[0]["iso_index"] == 8 and r["ok"]


def test_isolado_nao_depende_de_faixa_exclusiva(conectores, monkeypatch):
    agora = datetime.now(timezone.utc).isoformat()
    gw = {"id": "gw", "type": "ruijie", "tenant_slug": "t1", "gateway_host": "172.16.80.1", "last_seen": agora,
          "host": {"lan_networks": ["172.16.80.0/23"]}, "ruijie": {"lans": [{"gateway": "172.16.80.1"}]},
          "ruijie_poll": {"ok": True, "host": "172.16.80.1", "at": agora}}
    outro = {"id": "mk", "type": "routeros", "tenant_slug": "t2", "tunnel": {"client_lans": ["172.16.80.0/23"]}}
    cs._save_connectors([gw, outro])
    monkeypatch.setattr(cs, "get_current_tenant_slug", lambda: "t1")
    # legado (tabela geral): outro cliente na mesma faixa -> recusa
    assert cs.ruijie_gateway_owner("172.16.80.1") == ""
    # isolado: caminho exclusivo pelo IP virtual -> abre (a prova de posse continua valendo)
    monkeypatch.setattr(vnat, "_load_map", lambda: {
        "gw": [(vnat.ipaddress.ip_network("172.16.80.0/23"), vnat.ipaddress.ip_network("10.210.128.0/23"))]})
    assert cs.ruijie_gateway_owner("172.16.80.1") == "gw"
    monkeypatch.setattr(cs, "get_current_tenant_slug", lambda: "t2")
    assert cs.ruijie_gateway_owner("172.16.80.1") == ""


# ------------------------------------------------ correcoes do revisor (2a rodada)

def test_ovpn_com_comando_e_recusado_no_cadastro_e_limpo_no_sync():
    malicioso = "client\ndev tun\nremote 1.2.3.4 1194\nscript-security 2\nup \"/bin/sh -c 'iptables -P FORWARD ACCEPT'\"\n" \
                "plugin /usr/lib/openvpn/plugins/openvpn-plugin-down-root.so x\n<ca>\nup-linha-de-certificado\n</ca>\n"
    with pytest.raises(ValueError, match="executam comandos"):
        cs._valida_ovpn(malicioso)
    limpo = sync.ovpn_seguro(malicioso)
    assert "script-security" not in limpo and "\nup " not in limpo and "plugin" not in limpo
    assert "remote 1.2.3.4 1194" in limpo and "up-linha-de-certificado" in limpo  # bloco <ca> intacto
    cs._valida_ovpn("client\ndev tun\nremote 1.2.3.4 1194\nauth-user-pass\n")  # o do eWeb passa
    assert "--script-security 1" in sync.run_args("abc", 14)[-1]


def test_gateway_sempre_mapeado_e_faixa_do_servidor_recusada():
    locais = [prov.ipaddress.ip_network("172.18.0.0/16")]  # bridge Docker do servidor
    c = {"gateway_host": "172.16.80.1",
         "host": {"lan_networks": ["10.208.0.0/24", "172.18.5.0/24", "8.8.8.0/24", "172.16.0.0/16"]}}
    lans = prov._lans_ruijie(c, locais)
    # faixa virtual, rede Docker e IP publico nunca entram; a /16 entra mas nao cabe no slice
    assert lans == ["172.16.0.0/16"]
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(prov, "_redes_locais", lambda: locais)
    lans, vm = prov._vmap_cobrindo_gateway(14, c, lans, [])
    mp.undo()
    # /16 descartada pelo slice -> o /32 do gateway entra no lugar
    assert ("172.16.80.1/32" in [r for r, _v in vm])


def test_teardown_de_rjc_nao_derruba_mikrotik_que_herdou_o_indice(monkeypatch, tmp_path):
    conns = [{"id": "mk", "type": "routeros", "iso_index": 15,
              "tunnel": {"client_public_key": "pk", "client_lans": ["192.168.50.0/24"]}}]
    monkeypatch.setattr(prov, "VNAT_MAP", str(tmp_path / "map.json"))
    monkeypatch.setattr(prov, "wg_privkey", lambda: "k")
    monkeypatch.setattr(prov, "load_connectors", lambda: conns)
    monkeypatch.setattr(prov, "existing_wgc_indices", lambda: [15])
    monkeypatch.setattr(prov, "existing_rjc_indices", lambda: [15])  # rede Docker que sobrou
    monkeypatch.setattr(prov, "_apply", lambda *a: "wgc15 ok")
    _sh_falso(monkeypatch)
    derrubados = []
    monkeypatch.setattr(prov, "teardown_ruijie", lambda n: derrubados.append(n) or "x")
    prov.reconcile_once()
    assert derrubados == []


def test_mapa_perde_entrada_velha_no_slice_reaproveitado():
    mapa = {"apagado": [{"real_cidr": "192.168.9.0/24", "virtual_cidr": str(next(prov.virtual_slice(14).subnets(new_prefix=24)))}],
            "outro": [{"real_cidr": "10.1.0.0/24", "virtual_cidr": str(next(prov.virtual_slice(3).subnets(new_prefix=24)))}]}
    saida = prov._limpa_mapa_de_slice_reaproveitado(dict(mapa), {"gw": 14})
    assert "apagado" not in saida and "outro" in saida


def test_isolado_com_gateway_fora_do_mapa_nao_cai_no_ip_real(conectores, monkeypatch):
    agora = datetime.now(timezone.utc).isoformat()
    gw = {"id": "gw", "type": "ruijie", "tenant_slug": "t1", "gateway_host": "172.16.80.1", "last_seen": agora,
          "gateway_user": "admin", "password_enc": "x", "iso_index": 14,
          "host": {"lan_networks": ["172.16.80.0/23"]}, "ruijie": {"lans": [{"gateway": "172.16.80.1"}]},
          "ruijie_poll": {"ok": True, "host": "172.16.80.1", "at": agora}}
    cs._save_connectors([gw])
    monkeypatch.setattr(cs, "get_current_tenant_slug", lambda: "t1")
    # mapa do conector existe, mas nao cobre o gateway
    monkeypatch.setattr(vnat, "_load_map", lambda: {
        "gw": [(vnat.ipaddress.ip_network("192.168.110.0/24"), vnat.ipaddress.ip_network("10.211.128.0/24"))]})
    assert cs.ruijie_gateway_owner("172.16.80.1") == ""
    chamados = []
    monkeypatch.setattr(cs, "ruijie_collect_status", lambda host, *a, **k: chamados.append(host))
    with pytest.raises(ValueError, match="sem IP virtual"):
        cs._ruijie_poll_row(dict(gw))
    assert chamados == []


# ------------------------------------------------ correcoes do revisor (3a rodada)

def test_transicao_com_indice_e_sem_mapa_nunca_usa_ip_real(conectores, monkeypatch):
    agora = datetime.now(timezone.utc).isoformat()
    gw = {"id": "gw", "type": "ruijie", "tenant_slug": "t1", "gateway_host": "172.16.80.1", "last_seen": agora,
          "gateway_user": "admin", "password_enc": "x", "iso_index": 8,
          "host": {"lan_networks": ["172.16.80.0/23"]}, "ruijie": {"lans": [{"gateway": "172.16.80.1"}]},
          "ruijie_poll": {"ok": True, "host": "172.16.80.1", "at": agora}}
    cs._save_connectors([gw])
    monkeypatch.setattr(cs, "get_current_tenant_slug", lambda: "t1")
    monkeypatch.setattr(vnat, "_load_map", lambda: {})  # provisionador ainda nao gravou
    chamados = []
    monkeypatch.setattr(cs, "ruijie_collect_status", lambda host, *a, **k: chamados.append(host))
    with pytest.raises(ValueError, match="sem IP virtual"):
        cs._ruijie_poll_row(dict(gw))
    assert chamados == []  # a senha do gateway nao saiu
    assert cs.ruijie_gateway_owner("172.16.80.1") == ""


def test_indice_do_ruijie_pula_manuais_e_slice_ainda_no_mapa(monkeypatch):
    # slice 8 ainda tem entrada no mapa (conector que sobrou) -> pula para o 9
    s8 = next(prov.virtual_slice(8).subnets(new_prefix=24))
    monkeypatch.setattr(vnat, "_load_map", lambda: {"sobrou": [(vnat.ipaddress.ip_network("192.168.9.0/24"), s8)]})
    assert cs._next_ruijie_iso_index([{"iso_index": 1}, {"iso_index": 13}]) == 9


def test_provisionador_recusa_indice_dos_manuais(monkeypatch):
    feitos = _sh_falso(monkeypatch)
    assert "RECUSADO" in prov._apply_ruijie(1, "gw", ["172.16.80.0/23"], [])
    assert not any(a[:2] == ["ip", "route"] for a in feitos)


def test_diretiva_entre_aspas_tambem_e_barrada():
    cfg = 'client\ndev tun\n"plugin" /usr/lib/openvpn/plugins/openvpn-plugin-down-root.so "iptables -P FORWARD ACCEPT"\n'
    with pytest.raises(ValueError, match="plugin"):
        cs._valida_ovpn(cfg)
    assert "plugin" not in sync.ovpn_seguro(cfg)
    args = sync.run_args("abc", 14)
    assert args[args.index("--dns") + 1] == "8.8.8.8"


def test_mapa_so_e_gravado_depois_que_o_tunel_existe(monkeypatch, tmp_path):
    conns = [{"id": "gw", "type": "ruijie", "iso_index": 14, "gateway_host": "172.16.80.1",
              "host": {"lan_networks": ["172.16.80.0/23"]}}]
    monkeypatch.setattr(prov, "VNAT_MAP", str(tmp_path / "map.json"))
    monkeypatch.setattr(prov, "wg_privkey", lambda: "k")
    monkeypatch.setattr(prov, "load_connectors", lambda: conns)
    monkeypatch.setattr(prov, "existing_wgc_indices", lambda: [])
    monkeypatch.setattr(prov, "existing_rjc_indices", lambda: [])
    monkeypatch.setattr(prov, "_redes_locais", lambda: [])
    _sh_falso(monkeypatch, existe=False)  # rjc14 ainda nao existe
    logs = prov.reconcile_once()
    assert any("aguardando tunel" in l for l in logs)
    assert not (tmp_path / "map.json").exists() or "gw" not in json.loads((tmp_path / "map.json").read_text())
