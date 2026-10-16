"""Camera caida perde a ONU na coleta da OLT, mas o lugar onde ela estava fica
guardado em `onu_ultima` -- o tecnico acha a camera pela ONU instalada."""
from pathlib import Path

import app.services.scan_service as scan
from app.services.inventory_json import guardar_onu_ultima
from app.services.monitoring_service import _onu_da_camera

NADA = Path("/nao/existe.json")


def _cam():
    return {"ip": "10.0.0.5", "mac": "aa:bb:cc:dd:ee:01", "titulo": "CAM PRACA",
            "olt_name": "OLT CENTRO", "olt_ip": "10.1.1.1", "pon": "3", "onu_id": "17",
            "onu_name": "PRACA-POSTE-2", "onu_serial": "ITBS1234ABCD",
            "onu_rx": "-21.3", "onu_telemetry_updated_at": "2026-10-14T22:10:00+00:00"}


def _coleta(monkeypatch, cpes):
    monkeypatch.setattr(scan, "load_olt_cpe_state", lambda: {"cpes": cpes})


def test_camera_que_some_da_coleta_guarda_a_ultima_onu(monkeypatch):
    _coleta(monkeypatch, [{"cpe_mac": "ff:ff:ff:ff:ff:ff", "pon": "1", "onu_id": "1"}])
    rows, mudou = scan._enrich_inventory_with_olt([_cam()], NADA)
    cam = rows[0]
    assert mudou == 1
    # a ONU de agora some (dado velho nao pode parecer atual)...
    assert cam["pon"] == "" and cam["onu_id"] == "" and cam["onu_rx"] == ""
    # ...mas a pista de onde ela estava fica
    u = cam["onu_ultima"]
    assert (u["olt_name"], u["pon"], u["onu_id"], u["onu_name"], u["onu_serial"]) == \
        ("OLT CENTRO", "3", "17", "PRACA-POSTE-2", "ITBS1234ABCD")
    assert u["visto_em"] == "2026-10-14T22:10:00+00:00" and u["sumiu_em"]

    # coletas seguintes com a camera ainda fora nao mexem no registro
    antes = dict(u)
    rows, mudou = scan._enrich_inventory_with_olt(rows, NADA)
    assert mudou == 0 and rows[0]["onu_ultima"] == antes


def test_camera_que_volta_descarta_a_ultima(monkeypatch):
    cam = _cam()
    for k in ("pon", "onu_id", "onu_name", "onu_serial"):
        cam[k] = ""
    cam["onu_ultima"] = {"pon": "3", "onu_id": "17", "sumiu_em": "2026-10-15T00:00:00+00:00"}
    _coleta(monkeypatch, [{"cpe_mac": "aa:bb:cc:dd:ee:01", "pon": "4", "onu_id": "2", "onu_serial": "ITBS9"}])
    rows, mudou = scan._enrich_inventory_with_olt([cam], NADA)
    assert mudou == 1 and "onu_ultima" not in rows[0]
    assert (rows[0]["pon"], rows[0]["onu_id"]) == ("4", "2")


def test_digitado_a_mao_nao_vira_ultima(monkeypatch):
    cam = dict(_cam(), olt_manual=True)
    _coleta(monkeypatch, [])
    rows, _ = scan._enrich_inventory_with_olt([cam], NADA)
    assert rows[0]["onu_id"] == "17" and "onu_ultima" not in rows[0]


def test_sem_onu_nao_guarda_nada():
    assert guardar_onu_ultima({"ip": "1.1.1.1", "pon": "", "onu_id": ""}) is False


def test_monitoramento_mostra_atual_ou_ultima():
    assert _onu_da_camera(_cam())["onu"]["onu_id"] == "17"
    caida = {"ip": "1", "pon": "", "onu_id": "", "onu_ultima": {"pon": "3", "onu_id": "17", "sumiu_em": "x"}}
    assert _onu_da_camera(caida) == {"onu_ultima": {"pon": "3", "onu_id": "17", "sumiu_em": "x"}}
    assert _onu_da_camera({"ip": "1"}) == {}
