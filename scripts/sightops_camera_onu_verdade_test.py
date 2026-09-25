"""A tela de Cameras IP so pode mostrar ONU que EXISTE na coleta atual da OLT.

Bug real (2026-09-23, Barra de Sao Miguel): a ONU 0/1/26 tinha sido apagada da
OLT e as cameras continuavam exibindo PON/ONU/serial daquela ONU, porque o
valor ficava carimbado na linha do inventario e o cruzamento so sobrescrevia
quando achava o MAC. Regra do usuario: informacao falsa e pior do que ausente.

Roda: python scripts/sightops_camera_onu_verdade_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.scan_service import _OLT_LINK_FIELDS, _enrich_inventory_with_olt

SEM_ARQUIVO = Path("nao-existe-olt-cpe-macs.json")

COLETA_ATUAL = {
    "cpes": [
        # camera viva: MAC aprendido agora
        {"cpe_mac": "d8:36:5f:61:0c:5a", "pon": "0/4", "onu_id": "18", "onu_name": "LPR_Oiticica",
         "onu_serial": "98:e5:5b:44:11:22", "olt_ip": "100.65.10.200", "vlan": "3000"},
        # ONU existe, mas o MAC da camera nao foi aprendido nesta coleta
        {"cpe_mac": "aa:bb:cc:dd:ee:ff", "pon": "0/1", "onu_id": "30", "onu_name": "Escola_Nova",
         "onu_serial": "98:e5:5b:12:e4:2e", "olt_ip": "100.65.10.200", "vlan": "3000"},
    ]
}


def cam(ip, mac, **extra):
    base = {"ip": ip, "mac": mac, "titulo": f"CAM {ip}", "local": "Rua X", "lat": "-10.1", "lon": "-36.8",
            "snapshot_url": "/data/snapshot/x.jpg", "vlan": "3000"}
    base.update(extra)
    return base


def main() -> None:
    linhas = [
        # 1) casa pelo MAC: mostra o que a OLT diz agora
        cam("10.0.0.1", "d8:36:5f:61:0c:5a", pon="0/9", onu_id="99", onu_serial="serial-velho"),
        # 2) ONU renumerada (era 0/1/26): casa pelo SERIAL e mostra o numero NOVO
        cam("10.0.0.2", "00:00:00:00:00:02", pon="0/1", onu_id="26", onu_serial="98:e5:5b:12:e4:2e"),
        # 3) ONU apagada da OLT: some tudo (era o caso da ESCOLA MEDEA)
        cam("10.0.0.3", "00:00:00:00:00:03", pon="0/1", onu_id="26", onu_name="Escola_M",
            onu_serial="98:e5:5b:99:99:99", olt_ip="100.65.10.200", onu_oper_status="up"),
        # 4) camera que nunca teve ONU: nao muda nada
        cam("10.0.0.4", "00:00:00:00:00:04"),
    ]
    with patch("app.services.scan_service.load_olt_cpe_state", return_value=COLETA_ATUAL):
        saida, mudou = _enrich_inventory_with_olt(linhas, SEM_ARQUIVO)
    por_ip = {r["ip"]: r for r in saida}

    a = por_ip["10.0.0.1"]
    assert a["pon"] == "0/4" and a["onu_id"] == "18" and a["onu_serial"] == "98:e5:5b:44:11:22", a

    b = por_ip["10.0.0.2"]
    assert b["pon"] == "0/1" and b["onu_id"] == "30" and b["onu_name"] == "Escola_Nova", b

    c = por_ip["10.0.0.3"]
    assert all(not c.get(k) for k in _OLT_LINK_FIELDS), c
    # o que e da camera continua intacto
    assert c["titulo"] == "CAM 10.0.0.3" and c["local"] == "Rua X" and c["lat"] == "-10.1"
    assert c["snapshot_url"] and c["vlan"] == "3000" and c["mac"] == "00:00:00:00:00:03"

    d = por_ip["10.0.0.4"]
    assert not d.get("pon") and d["titulo"] == "CAM 10.0.0.4", d
    assert mudou >= 2, mudou

    # 5) sem coleta nenhuma: nada pode ser afirmado -> colunas vazias
    linhas2 = [cam("10.0.0.5", "00:00:00:00:00:05", pon="0/1", onu_id="26", onu_serial="x")]
    with patch("app.services.scan_service.load_olt_cpe_state", return_value={}):
        saida2, _ = _enrich_inventory_with_olt(linhas2, SEM_ARQUIVO)
    assert all(not saida2[0].get(k) for k in _OLT_LINK_FIELDS), saida2[0]
    assert saida2[0]["titulo"] == "CAM 10.0.0.5"

    print("OK cameras: PON/ONU so aparece se existir na coleta atual (MAC ou serial); senao, vazio")


if __name__ == "__main__":
    main()
