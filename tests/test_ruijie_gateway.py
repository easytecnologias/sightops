"""Gateway Ruijie Reyee como conector: coleta automatica, formato do MikroTik,
status de verdade e APs no monitoramento."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.cli.tools import ruijie_reyee as rj
from app.services import connector_service as cs
from app.services import monitoring_service as ms

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ruijie" / "eg105g_status.json").read_text(encoding="utf-8"))


def _parse():
    f = {k: v for k, v in FIXTURE.items() if not k.startswith("_")}
    return rj.parse_status(f.pop("sysinfo"), **f)


def test_inventario_sai_no_formato_do_mikrotik():
    inv = _parse()["inventory"]
    assert {"ip": "172.16.80.200", "mac": "08:cc:81:00:00:12", "interface": "br-lan_300"} in inv["arp_rows"]
    nvr = next(r for r in inv["dhcp_rows"] if r["ip"] == "172.16.80.200")
    assert nvr["host"] == "DS-7632NXI-K2" and nvr["port"] == "LAN3/WAN1" and nvr["status"] == "bound"
    # aparelho desconectado sem IP nao vira lease
    assert all(r["ip"] for r in inv["dhcp_rows"])
    assert inv["arp_entries"] == 3 and inv["dhcp_leases"] == 2
    # o mesmo formato "ip|mac|..." que access_control_device e deployments leem
    assert "172.16.80.200|08:cc:81:00:00:12|" in inv["arp_sample"]
    assert inv["lan_networks"] == ["172.16.80.0/23", "172.16.180.0/24"]
    assert inv["neighbor_rows"] == [{"ip": "172.16.80.4", "mac": "10:82:3d:00:00:02",
                                     "identity": "G1RUAGG000002", "platform": "RAP6262"}]


def test_senha_do_pppoe_nunca_sai_da_coleta():
    texto = json.dumps(_parse(), ensure_ascii=False)
    assert "SENHA-PPPOE-NAO-PODE-VAZAR" not in texto
    assert "usuario_pppoe" not in texto


def test_host_portas_alarmes():
    out = _parse()
    host = out["host"]
    assert host["hostname"] == "GW-TESTE"  # nome do devRemark casado pelo MAC "1082.3d00.0001"
    assert host["model"] == "EG105G-P-V2" and host["firmware"] == "ReyeeOS 2.340.0.1629"
    assert host["wan_ip"] == "203.0.113.10" and host["wan_proto"] == "pppoe"
    r = out["ruijie"]
    assert [p["up"] for p in r["ports"]] == [True, False, True]
    assert r["wan_down_bps"] == 36503522 and r["wan_up_bps"] == 3977271
    assert r["alarms"][0]["sn"] == "G1RUAGG000002"
    assert r["alarms"][0]["msg"].startswith("Alimentacao insuficiente")
    assert r["ip_conflict"] is False


def test_modulo_ausente_nao_quebra_o_parse():
    out = rj.parse_status(FIXTURE["sysinfo"], None, None, None, None, None, None, None, None, None)
    assert out["inventory"]["arp_rows"] == [] and out["ruijie"]["aps"] is None
    assert out["host"]["serial"] == "H1SU000000001"


def test_so_leitura():
    with pytest.raises(ValueError):
        rj._get(None, "devConfig.set", "port_mapping")  # type: ignore[arg-type]


@pytest.fixture
def conectores(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CONNECTORS_PATH", tmp_path / "connectors.json")
    monkeypatch.setattr(cs, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cs, "decrypt", lambda v: "senha")
    cs._ruijie_sessions.clear()
    cs._save_connectors([{"id": "gw1", "type": "ruijie", "tenant_slug": "t1", "name": "GW", "site": "S",
                          "gateway_host": "203.0.113.10", "gateway_user": "admin", "password_enc": "x",
                          "last_seen": "", "inventory": {"known_targets": ["172.16.80.9"]}}])
    return cs


def _coleta_ok(*a, **k):
    out = _parse()
    out.update(ok=True, sn="H1SU000000001", module_errors=[], session="sessao")
    return out


def test_coleta_grava_e_deixa_online(conectores, monkeypatch):
    monkeypatch.setattr(cs, "ruijie_collect_status", _coleta_ok)
    assert cs.ruijie_poll_all() == {"total": 1, "ok": 1, "erros": {}}
    row = cs._load_connectors()[0]
    assert cs._public_connector(row)["status"] == "online"
    assert row["inventory"]["known_targets"] == ["172.16.80.9"]  # nao apaga o que veio de outro lugar
    assert row["inventory"]["arp_rows"] and row["ruijie_poll"]["ok"] is True
    assert "G1RUAGG000002" in row["ruijie_aps_known"]
    assert cs._ruijie_sessions["gw1"] == "sessao"  # reaproveita o login no proximo ciclo
    assert "SENHA-PPPOE" not in json.dumps(row)


def test_gateway_mudo_nao_fica_online_o_dia_todo(conectores, monkeypatch):
    monkeypatch.setattr(cs, "ruijie_collect_status", _coleta_ok)
    cs.ruijie_poll_all()

    def caiu(*a, **k):
        raise TimeoutError("timed out")
    monkeypatch.setattr(cs, "ruijie_collect_status", caiu)
    resumo = cs.ruijie_poll_all()
    assert resumo["ok"] == 0 and "gw1" in resumo["erros"]
    row = cs._load_connectors()[0]
    assert row["ruijie_poll"]["ok"] is False and "gw1" not in cs._ruijie_sessions
    # 3 ciclos sem resposta -> offline (antes: 24 h)
    velho = datetime.now(timezone.utc) - timedelta(seconds=cs.RUIJIE_POLL_INTERVAL_S * 3 + 5)
    row["last_seen"] = velho.isoformat()
    assert cs._public_connector(row)["status"] == "offline"


def _conector_publico(status="online", ok=True, aps_atuais=True):
    out = _parse()
    ruijie = dict(out["ruijie"])
    if not aps_atuais:
        ruijie["aps"] = []
    return {"id": "gw1", "type": "ruijie", "site": "S", "status": status, "host": out["host"], "ruijie": ruijie,
            "ruijie_poll": {"ok": ok, "at": "2026-10-19T12:00:00+00:00", "error": "" if ok else "timeout"},
            "ruijie_aps_known": {"G1RUAGG000002": {**out["ruijie"]["aps"][0], "last_seen": "x"}}}


def test_detalhe_do_conector_vai_para_o_zabbix():
    d = ms._detalhe_conector(_conector_publico())
    assert d["ports_total"] == 3 and d["ports_up"] == 2
    assert d["uplink_in_bps"] == 36503522 and d["alertas"] == 1 and d["checado_em"]
    # sem coleta valida nao manda numero (0 viraria "nenhuma porta com link")
    d = ms._detalhe_conector(_conector_publico(ok=False))
    assert "ports_up" not in d and "alertas" not in d and d["poll_error"] == "timeout"
    # MikroTik continua so com last_seen
    assert ms._detalhe_conector({"type": "routeros", "last_seen": "a"}) == {"last_seen": "a"}


def test_ap_que_some_do_gateway_vira_down_e_nao_e_apagado():
    [ap] = ms._access_point_entities([_conector_publico()])
    assert ap["status"] == "online" and ap["entity_type"] == "access_point"
    assert ap["detail"]["alertas"] == 1 and ap["parent_key"] == "connector:gw1"
    [ap] = ms._access_point_entities([_conector_publico(aps_atuais=False)])
    assert ap["status"] == "offline"
    # gateway sem coleta: nao da para dizer que o AP caiu
    [ap] = ms._access_point_entities([_conector_publico(status="offline", ok=False)])
    assert ap["status"] == "unknown" and "alertas" not in ap["detail"]


def test_modulo_que_falhou_e_nao_sei_e_nao_zero():
    f = {k: v for k, v in FIXTURE.items() if not k.startswith("_")}
    f.update(neighbor=None, ports=None, alarms=None)
    out = rj.parse_status(f.pop("sysinfo"), **f)["ruijie"]
    assert out["aps"] is None and out["ports"] is None and out["alarms"] is None
    c = _conector_publico()
    c["ruijie"] = {**c["ruijie"], "ports": None, "alarms": None, "aps": [], "aps_ok": False}
    d = ms._detalhe_conector(c)
    assert "ports_up" not in d and "alertas" not in d and d["uplink_in_bps"] == 36503522
    # sem o modulo de vizinhos, nenhum AP vira offline
    [ap] = ms._access_point_entities([c])
    assert ap["status"] == "unknown"


def test_vizinho_que_nao_e_ap_nao_vira_access_point():
    viz = {"neighbor": [dict(FIXTURE["neighbor"]["neighbor"][0]),
                        {"role": "ES", "product": "ESW", "deviceType": "ES209GC-P", "devSN": "SW1", "ip": "172.16.80.5", "devMac": "10:82:3d:00:00:09"}]}
    f = {k: v for k, v in FIXTURE.items() if not k.startswith("_")}
    f["neighbor"] = viz
    out = rj.parse_status(f.pop("sysinfo"), **f)
    assert [a["sn"] for a in out["ruijie"]["aps"]] == ["G1RUAGG000002"]
    assert len(out["inventory"]["neighbor_rows"]) == 2


def test_conector_offline_nao_repete_numero_velho():
    d = ms._detalhe_conector(_conector_publico(status="offline"))
    assert "uplink_in_bps" not in d and "ports_up" not in d


def test_coleta_nao_grava_em_conector_de_outro_cliente_com_mesmo_id(conectores, monkeypatch):
    def troca_no_meio(*a, **k):
        # durante a coleta o conector e apagado e outro cliente cria um com o mesmo id
        cs._save_connectors([{"id": "gw1", "type": "ruijie", "tenant_slug": "t2", "gateway_host": "198.51.100.7",
                              "password_enc": "y", "inventory": {}}])
        return _coleta_ok()
    monkeypatch.setattr(cs, "ruijie_collect_status", troca_no_meio)
    cs.ruijie_poll_all()
    row = cs._load_connectors()[0]
    assert row["tenant_slug"] == "t2" and row["inventory"] == {} and "ruijie" not in row


def test_erro_do_gateway_nao_guarda_resposta_crua():
    class S:
        def call(self, *a, **k):
            return {"code": 1, "error": "falhou", "data": [{"wan": [{"password": "SEGREDO"}]}]}
    with pytest.raises(RuntimeError) as e:
        rj._get(S(), "devConfig.get", "network")  # type: ignore[arg-type]
    assert "SEGREDO" not in str(e.value)


def test_telegram_avisa_alarme_de_ap(monkeypatch):
    from app.services import telegram_notification_service as tg
    estado, enviados = {}, []
    monkeypatch.setattr(tg, "load_app_settings", lambda: {"telegram_notifications": {
        "enabled": True, "bot_token": "t", "chat_id": "c"}})
    monkeypatch.setattr(tg, "_send", lambda cfg, msg: enviados.append(msg) or {"ok": True})
    monkeypatch.setattr(tg, "_state", lambda k, t: estado.get((k, t), {}))
    monkeypatch.setattr(tg, "_set_state", lambda k, t, a, v: estado.__setitem__((k, t), {"active": a, "last_value": v}))
    [ap] = ms._access_point_entities([_conector_publico()])
    linha = {"entity_key": ap["entity_key"], "entity_type": "access_point", "status": "up",
             "display_name": ap["display_name"], "site": "S", "detail_json": json.dumps(ap["detail"])}
    monkeypatch.setattr(tg, "list_entities", lambda limit=2000: [linha])
    tg.process_monitoring_notifications()
    tg.process_monitoring_notifications()  # mesmo alarme: nao repete
    assert len(enviados) == 1 and "ALARME NO EQUIPAMENTO" in enviados[0] and "Alimentacao insuficiente" in enviados[0]
