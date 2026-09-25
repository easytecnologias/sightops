"""clear_olt_link: apaga o vinculo de OLT das cameras SEM apagar camera nenhuma.

Roda: python scripts/sightops_olt_link_clear_test.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import db_store
from app.services.inventory_json import OLT_LINK_FIELDS, clear_olt_link, load_inventory_json, save_inventory_json


def _camera(ip: str, site: str, com_olt: bool = True) -> dict:
    row = {
        "ip": ip, "site": site, "titulo": f"CAM {ip}", "local": "Rua X",
        "lat": "-10.1", "lon": "-36.8", "vlan": "3000", "mac": "aa:bb:cc:dd:ee:ff",
        "snapshot_url": "/data/snapshot/x.jpg", "zabbix_hostid": "123",
    }
    if com_olt:
        row.update({"olt_ip": "100.65.10.200", "pon": "0/4", "onu_id": "6",
                    "onu_name": "ONU-T", "onu_serial": "98:2a:0a:9", "onu_oper_status": "up"})
    return row


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sightops-oltlink-") as tmp:
        db_store.SIGHTOPS_DB_PATH = Path(tmp) / "t.db"
        db_store.init_db()
        token = set_current_tenant_slug("cliente-teste")
        try:
            save_inventory_json([
                _camera("10.0.0.1", "BARRA"), _camera("10.0.0.2", "BARRA"),
                _camera("10.0.0.3", "SANTANA"), _camera("10.0.0.4", "BARRA", com_olt=False),
            ], mode="olt")

            out = clear_olt_link(site="barra")  # sem diferenciar maiuscula/minuscula
            assert out["cleared"] == 2, out  # a 3a e de outro site, a 4a ja estava sem vinculo

            rows = load_inventory_json(mode="olt")
            assert len(rows) == 4, "nenhuma camera pode sumir"
            por_ip = {r["ip"]: r for r in rows}

            barra = por_ip["10.0.0.1"]
            assert all(not barra.get(f) for f in OLT_LINK_FIELDS), barra
            # o que NAO e da OLT continua intacto
            assert barra["titulo"] == "CAM 10.0.0.1" and barra["local"] == "Rua X"
            assert barra["lat"] == "-10.1" and barra["vlan"] == "3000"
            assert barra["snapshot_url"] and barra["zabbix_hostid"] == "123"

            outro = por_ip["10.0.0.3"]
            assert outro["pon"] == "0/4" and outro["onu_serial"] == "98:2a:0a:9", "outro site foi afetado"

            # rodar de novo nao muda nada
            assert clear_olt_link(site="BARRA")["cleared"] == 0

            # sem site = todos
            assert clear_olt_link()["cleared"] == 1  # so sobrou SANTANA com vinculo
            assert len(load_inventory_json(mode="olt")) == 4

        finally:
            reset_current_tenant_slug(token)
    print("OK clear_olt_link: limpa so as colunas da OLT, so do site pedido, sem perder camera")


if __name__ == "__main__":
    main()
