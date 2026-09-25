"""Apagar a tabela da OLT por site tem que levar tambem as linhas SEM site.

O bug real (2026-09-23): a coleta gravava as linhas sem o campo `site`, entao
"apagar o site X" deixava tudo para tras e as cameras continuavam mostrando
PON/ONU na tela (o /api/cameras enriquece com esse estado na hora da leitura).

Roda: python scripts/sightops_olt_clear_por_site_test.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import db_store, olt_service

OLTS = [
    {"id": 1, "ip": "100.65.10.200", "site": "BARRA DE SAO MIGUEL", "name": "OLT - BARRA"},
    {"id": 2, "ip": "100.64.10.5", "site": "SANTANA", "name": "OLT - SANTANA"},
]

ESTADO = {
    "olt": {},
    "cpes": [
        {"cpe_mac": "aa:aa:aa:aa:aa:01", "olt_ip": "100.65.10.200", "pon": "0/4", "onu_id": "18"},   # sem site (legado)
        {"cpe_mac": "aa:aa:aa:aa:aa:02", "olt_ip": "100.65.10.200", "pon": "0/4", "onu_id": "21"},   # sem site (legado)
        {"cpe_mac": "bb:bb:bb:bb:bb:01", "olt_ip": "100.65.10.200", "site": "BARRA DE SAO MIGUEL"},  # com site
        {"cpe_mac": "cc:cc:cc:cc:cc:01", "olt_ip": "100.64.10.5", "site": "SANTANA"},                # outro site
        {"cpe_mac": "cc:cc:cc:cc:cc:02", "olt_ip": "100.64.10.5"},                                   # outro site, sem site
    ],
}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sightops-oltclear-") as tmp:
        db_store.SIGHTOPS_DB_PATH = Path(tmp) / "t.db"
        db_store.init_db()
        token = set_current_tenant_slug("cliente-teste")
        try:
            with patch("app.services.olt_registry.list_olts", return_value=OLTS):
                olt_service.save_olt_cpe_state(ESTADO)

                out = olt_service.clear_macs(site="BARRA DE SAO MIGUEL")
                assert out["removed_rows"] == 3, out  # 2 sem site + 1 com site
                assert out["remaining"] == 2, out

                restantes = list((olt_service.load_olt_cpe_state() or {}).get("cpes") or [])
                assert all(r["olt_ip"] == "100.64.10.5" for r in restantes), restantes
                assert {r["cpe_mac"] for r in restantes} == {"cc:cc:cc:cc:cc:01", "cc:cc:cc:cc:cc:02"}

                # site sem OLT cadastrada nao derruba nada de outro site
                out2 = olt_service.clear_macs(site="SITE QUE NAO EXISTE")
                assert out2["removed_rows"] == 0 and out2["remaining"] == 2, out2

                assert olt_service.site_da_olt("100.64.10.5") == "SANTANA"
                assert olt_service.site_da_olt("1.2.3.4") == ""
        finally:
            reset_current_tenant_slug(token)
    print("OK apagar OLT por site: leva as linhas sem site daquela OLT e nao toca nos outros sites")


if __name__ == "__main__":
    main()
