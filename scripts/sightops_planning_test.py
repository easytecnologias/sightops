"""Valida projetos planejados, geracao em lote, CSV e isolamento SaaS."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="sightops-planning-test-"))
    os.environ["DATA_DIR"] = str(tmp / "data")
    os.environ["SIGHTOPS_DB_PATH"] = str(tmp / "data" / "sightops.db")
    os.environ["DATABASE_BACKEND"] = "sqlite"
    os.environ["ENABLE_LEGACY_STATE_IMPORT"] = "0"
    os.environ.pop("DATABASE_URL", None)

    from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
    from app.services import db_store, planning_service

    db_store.init_db()

    token = set_current_tenant_slug("cliente-a")
    try:
        project = planning_service.save_project({
            "name": "Projeto Reserva", "client_name": "Condominio Reserva", "status": "draft"
        })
        site = planning_service.save_site(project["id"], {"name": "PORTARIA"})
        olt = planning_service.save_device(project["id"], {
            "device_type": "olt", "name": "OLT RESERVA", "ip": "10.20.0.2", "site_id": site["id"]
        })
        onu = planning_service.save_device(project["id"], {
            "device_type": "onu", "name": "PON 1 / ONU 1", "parent_id": olt["id"],
            "site_id": site["id"], "pon": "1", "onu_position": "1",
        })
        generated = planning_service.generate_devices(project["id"], {
            "device_type": "camera", "site_id": site["id"], "parent_id": onu["id"],
            "start_ip": "10.20.10.20", "count": 3, "first_number": 1, "digits": 2,
            "name_template": "{number} - ENTRADA", "manufacturer": "Intelbras", "model": "VIP 3230 B",
        })
        check([row["ip"] for row in generated] == ["10.20.10.20", "10.20.10.21", "10.20.10.22"], "faixa de IP incorreta")
        check([row["name"] for row in generated] == ["01 - ENTRADA", "02 - ENTRADA", "03 - ENTRADA"], "sequencia de nomes incorreta")

        csv_result = planning_service.import_csv(
            project["id"],
            "tipo;nome;ip;site;fabricante;modelo;latitude;longitude\n"
            "camera;04 - PLAYGROUND;10.20.10.23;LAZER;Intelbras;VIP 3230 B;-9,75;-36,66\n".encode(),
            {"device_type": "camera"},
        )
        check(csv_result["imported"] == 1, f"CSV nao importou: {csv_result}")
        detail = planning_service.get_project(project["id"]) or {}
        check(len(detail.get("sites") or []) == 2, "site do CSV nao foi criado")
        check(len(detail.get("devices") or []) == 6, "total de equipamentos planejados incorreto")
        check(planning_service.list_projects()[0]["cameras_count"] == 4, "contador de cameras duplicou pelos sites")
        catalog = planning_service.list_equipment_catalog()
        check(any(row["device_type"] == "camera" and row["manufacturer"] == "Intelbras" and row["model"] == "VIP 3230 B" for row in catalog), "catalogo nao trouxe modelo usado no projeto")
        check(any(row["device_type"] == "olt" and row["model"] == "8820i" for row in catalog), "catalogo conhecido nao trouxe modelo de OLT")
        assembled = planning_service.assemble_gpon_box(project["id"], {
            "box_name": "CX-01", "site_id": site["id"], "latitude": -9.75, "longitude": -36.66,
            "onu_count": 1, "onu_manufacturer": "Intelbras", "onu_model": "R1v2", "pon": "2", "onu_position": "7",
            "include_cto": True, "cto_model": "CTO 1x8", "distribution_type": "switch", "distribution_count": 1,
            "port_capacity": 8, "camera_count": 5, "camera_start_ip": "10.20.30.1", "camera_name_template": "{number} - CAIXA",
        })
        check(len(assembled["items"]) == 9, "montagem da caixa GPON criou quantidade incorreta")
        check(len(assembled["cameras"]) == 5 and assembled["cameras"][0]["ip"] == "10.20.30.1", "cameras da caixa nao foram geradas")
        assembled_detail = planning_service.get_project(project["id"]) or {}
        switch = next(row for row in assembled_detail["devices"] if row["device_type"] == "switch" and row["name"].startswith("CX-01"))
        check(switch["metadata"].get("port_capacity") == 8, "capacidade do switch nao foi preservada")
        hierarchy_csv = planning_service.import_csv(
            project["id"],
            ("tipo;nome;site;equipamento_pai;metadata\n"
             "camera;CAM HIERARQUIA;PORTARIA;SW HIERARQUIA;{}\n"
             "switch;SW HIERARQUIA;PORTARIA;CX HIERARQUIA;{}\n"
             "box;CX HIERARQUIA;PORTARIA;;{}\n").encode(),
            {},
        )
        check(hierarchy_csv["imported"] == 3 and not hierarchy_csv["errors"], f"CSV hierarquico falhou: {hierarchy_csv}")
        hierarchy_detail = planning_service.get_project(project["id"]) or {}
        hierarchy_by_name = {row["name"]: row for row in hierarchy_detail["devices"]}
        check(hierarchy_by_name["CAM HIERARQUIA"]["parent_name"] == "SW HIERARQUIA", "camera nao foi ligada ao switch pelo CSV")
        check(hierarchy_by_name["SW HIERARQUIA"]["parent_name"] == "CX HIERARQUIA", "switch nao foi colocado dentro da caixa pelo CSV")
    finally:
        reset_current_tenant_slug(token)

    token = set_current_tenant_slug("cliente-b")
    try:
        check(planning_service.list_projects() == [], "tenant B enxergou projeto do tenant A")
        other = planning_service.save_project({"name": "Projeto B"})
        planning_service.save_device(other["id"], {"device_type": "camera", "name": "CAM B", "ip": "10.20.10.20"})
        check(len(planning_service.get_project(other["id"])["devices"]) == 1, "IP privado repetido entre tenants colidiu")
        check(planning_service.delete_project(project["id"]) is False, "tenant B excluiu projeto do tenant A")
    finally:
        reset_current_tenant_slug(token)

    token = set_current_tenant_slug("cliente-a")
    try:
        check(planning_service.delete_project(project["id"]) is True, "projeto nao foi excluido")
        with db_store._conn() as conn:
            remaining = conn.execute("SELECT COUNT(1) AS n FROM planning_devices WHERE project_id=?", (project["id"],)).fetchone()["n"]
        check(int(remaining) == 0, "exclusao do projeto nao removeu equipamentos em cascata")
    finally:
        reset_current_tenant_slug(token)

    if FAILURES:
        print(f"FALHOU ({len(FAILURES)}):")
        for failure in FAILURES:
            print(" -", failure)
        raise SystemExit(1)
    print("OK planejamento: geracao, CSV, hierarquia, cascata e tenants isolados")


if __name__ == "__main__":
    main()
